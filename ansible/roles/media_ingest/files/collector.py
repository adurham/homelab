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

# chat-id -> gallery folder (must match the gallery's known folders)
CHAT_NAMES = {
    "100000001": "person1", "100000002": "person2", "100000003": "person3",
    "100000004": "person4", "100000005": "person5", "777000": "upstream source",
}

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
    return CHAT_NAMES.get(str(chat_id), sanitize(name))


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
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
