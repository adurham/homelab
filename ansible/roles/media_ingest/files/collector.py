#!/usr/bin/env python3
"""
upstream source ephemeral collector (collector edition) — captures ephemeral media in
real time and PUSHES it to the gallery platform via the authenticated ingest
API. No rclone, no crypt key, no GDrive here: this box only holds the upstream source
session and the gallery OAuth2 client creds.

On an incoming ephemeral (ttl_seconds) message sent TO us:
  1. silent download to a tmpfs staging dir (no read receipt fired)
  2. resolve the destination folder = the chat's gallery folder name
  3. push to the gallery with stem=<chatid>_<msgid>, the real message date,
     out=False (received). The gallery encrypts + stores + thumbnails.
  4. delete the local staging file.

Folder naming mirrors the gallery's CHAT_NAMES map so captures land in the same
folders as the historical archive.
"""
import asyncio
import datetime as dt
import logging
import os
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient as SourceClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")
STAGING = Path(os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging"))
LOG_FILE = os.environ.get("TG_LOG_FILE", "/var/log/media-ingest/collector.log")

# chat-id -> gallery folder, STATIC SEED. On startup these are pushed into
# folder_meta.json (the single source of truth) for any chat-id not already
# mapped there — so after first run the UI map is authoritative, the map
# survives renames, and you manage everything from the gallery. This dict is
# only a bootstrap/fallback; edit mappings in the gallery UI, not here.
CHAT_NAMES = {
    "100000001": "person1", "100000002": "person2", "100000003": "person3",
    "100000004": "person4", "100000005": "person5", "777000": "upstream source",
}


def _seed_static_chat_ids():
    """One-time on startup: push CHAT_NAMES entries into folder_meta for any
    chat-id not already mapped there. Makes folder_meta the single source of
    truth without losing the historical static mappings."""
    try:
        import store_client
        meta = store_client.get_folder_meta() or {}
        mapped = set()
        for entry in meta.values():
            for cid in (entry.get("chat_ids") or []):
                mapped.add(str(cid))
        # group unmapped static entries by their target folder
        to_add = {}
        for cid, folder in CHAT_NAMES.items():
            if str(cid) not in mapped:
                to_add.setdefault(folder, []).append(str(cid))
        for folder, cids in to_add.items():
            existing = (meta.get(folder, {}).get("chat_ids") or [])
            store_client.set_chat_ids(folder, sorted(set(existing) | set(cids)))
            log.info("seeded folder_meta: %s -> %s", folder, cids)
        if to_add:
            log.info("folder_meta seed complete (%d folder(s))", len(to_add))
    except Exception as e:  # noqa: BLE001
        log.warning("folder_meta seed skipped: %s", e)

# Cached chat-id -> folder map fetched from the gallery's folder_meta.json.
_dyn_map = {}
_dyn_map_ts = 0.0
_DYN_TTL = 60.0  # refresh at most once a minute


def _refresh_dynamic_map():
    """Pull folder_meta from the gallery and build chat_id -> folder. Best-effort;
    on any failure we keep the last good map (or empty -> static fallback)."""
    global _dyn_map, _dyn_map_ts
    import time as _t
    if _t.time() - _dyn_map_ts < _DYN_TTL:
        return
    _dyn_map_ts = _t.time()
    try:
        import store_client
        meta = store_client.get_folder_meta()  # {folder: {chat_ids:[...]}}
        m = {}
        for folder, entry in (meta or {}).items():
            for cid in (entry.get("chat_ids") or []):
                m[str(cid)] = folder
        _dyn_map = m
    except Exception as e:  # noqa: BLE001
        log.debug("folder_meta refresh failed: %s", e)

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("collector-collector")
logging.getLogger("telethon").setLevel(logging.WARNING)


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


def folder_for(chat_id, name):
    # 1) dynamic UI map (rename-safe, user-controlled) wins
    _refresh_dynamic_map()
    cid = str(chat_id)
    if cid in _dyn_map:
        return _dyn_map[cid]
    # 2) static fallback map
    if cid in CHAT_NAMES:
        return CHAT_NAMES[cid]
    # 3) sanitized chat title (or 'unknown')
    return sanitize(name)


def ttl_of(media):
    if isinstance(media, (MessageMediaPhoto, MessageMediaDocument)):
        return getattr(media, "ttl_seconds", None)
    return None


async def handle(event):
    msg = event.message
    if getattr(msg, "out", False):
        return  # only media sent TO us
    media = getattr(msg, "media", None)
    if media is None or not ttl_of(media):
        return
    chat = await event.get_chat()
    cid = event.chat_id
    folder = folder_for(cid, getattr(chat, "title", None) or getattr(chat, "first_name", None))
    stem = f"{cid}_{msg.id}"
    date_iso = msg.date.isoformat() if msg.date else ""
    log.info("EPHEMERAL from chat=%s stem=%s -> folder=%s", cid, stem, folder)

    tmp = STAGING / stem
    try:
        path = await msg.download_media(file=str(tmp))
        if not path or os.path.getsize(path) == 0:
            log.warning("empty download for %s", stem)
            return
        store_client.push_media(folder, path, stem, date_iso, is_out=False)
        log.info("PUSHED %s to gallery folder %s", stem, folder)
    except Exception as e:  # noqa: BLE001
        log.error("capture/push failed %s: %s: %s", stem, type(e).__name__, e)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
        for p in STAGING.glob(stem + "*"):
            try:
                p.unlink()
            except OSError:
                pass


async def main():
    client = SourceClient(SESSION, API_ID, API_HASH)
    client.add_event_handler(handle, events.NewMessage(incoming=True))
    client.add_event_handler(handle, events.MessageEdited(incoming=True))
    await client.connect()
    if not await client.is_user_authorized():
        log.error("SESSION NOT AUTHORIZED — run login on this box first."); sys.exit(2)
    me = await client.get_me()
    log.info("Collector collector online as %s (id=%s). Listening...",
             getattr(me, "username", None) or getattr(me, "first_name", "?"), me.id)
    # sanity: confirm gallery auth works at startup
    try:
        ex = store_client.get_excluded()
        log.info("gallery auth OK; %d excluded stems", len(ex))
    except Exception as e:  # noqa: BLE001
        log.error("gallery auth FAILED at startup: %s", e)
    # one-time: seed the static chat-id map into folder_meta (single source of truth)
    _seed_static_chat_ids()
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
