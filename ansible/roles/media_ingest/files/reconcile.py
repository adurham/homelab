#!/usr/bin/env python3
"""
Reconcile sweep (collector edition) — periodic backstop that re-scans recent
private-chat history and pushes any incoming media the live collector missed
(restart/disconnect gaps, a message that arrived before a deploy, etc.).

This is the belt-and-suspenders companion to the live collector's catch_up:
catch_up handles the reconnect difference; this sweep guarantees eventual
consistency by independently walking the last N messages of each private 1:1
chat on a timer and pushing anything not already in the gallery.

Design (matches collector.py semantics exactly):
  * INCOMING only (msg.out == False) — never our own sent media.
  * PRIVATE 1:1 chats only.
  * photos, videos (incl. gifs / round notes), image|video documents; skip
    stickers / voice / non-media docs. Ephemeral included.
  * route chat-id -> folder via the gallery's folder_meta (rename-safe), exactly
    like the live collector — NOT the empty static map. Falls back to the
    sanitized chat title only if folder_meta has no mapping.
  * skip stems in the gallery exclusion ledger (trashed/purged).
  * idempotent: the gallery dedups by stem, so re-pushing an existing item is a
    no-op. A per-run in-memory _seen guards against album/duplicate work.

Bounded work: scans at most LOOKBACK messages per dialog (default 40), so each
run is cheap and the timer can fire often. The gallery's stem-dedup means we
never need a perfect checkpoint — overlap is free.

Env: TG_API_ID, TG_API_HASH, TG_SESSION (+ store_client env). Flags:
  --lookback N   messages per dialog to scan (default 40)
  --dialogs S..  restrict to dialog-name substrings
  --dry-run      report what WOULD be pushed, download/push nothing
"""
import argparse
import asyncio
import glob
import logging
import os
import sys
from pathlib import Path

from telethon import TelegramClient as SourceClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
# The live collector holds collector.session's SQLite open. Two processes on one
# .session file cause lock contention, so the sweep runs on a SEPARATE session
# file that is a fresh copy of the collector's auth (the source allows multiple
# concurrent connections on one authorization). We copy it at startup.
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/collector")
RECONCILE_SESSION = os.environ.get("TG_RECONCILE_SESSION", "/var/lib/media-ingest/reconcile")
STAGING = Path(os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging"))
LOG_FILE = os.environ.get("TG_RECONCILE_LOG", "/var/log/media-ingest/reconcile.log")

STAGING.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("reconcile")
logging.getLogger("telethon").setLevel(logging.WARNING)


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


def media_kind(msg):
    """Identical classification to collector.py: photo/video/media-doc or None."""
    if getattr(msg, "sticker", None):
        return None
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None) or getattr(msg, "video_note", None) or getattr(msg, "gif", None):
        return "video"
    doc = getattr(msg, "document", None)
    if doc is not None:
        mt = getattr(doc, "mime_type", "") or ""
        if mt.startswith("image/") or mt.startswith("video/"):
            return "media-doc"
    return None


def build_folder_map():
    """chat_id -> folder from the gallery's folder_meta (rename-safe routing)."""
    try:
        meta = store_client.get_folder_meta() or {}
    except Exception as e:  # noqa: BLE001
        log.warning("folder_meta fetch failed (%s); using sanitized titles only", e)
        return {}
    m = {}
    for folder, entry in meta.items():
        for cid in (entry.get("chat_ids") or []):
            m[str(cid)] = folder
    return m


def _ensure_session_copy():
    """Copy the collector's authorized session to the reconcile session path so
    the sweep doesn't contend on the live SQLite. Refresh each run so a re-auth
    of the collector propagates. No-op if the source session is missing."""
    import shutil
    src = SESSION + ".session"
    dst = RECONCILE_SESSION + ".session"
    if not os.path.exists(src):
        log.error("collector session %s missing — cannot run sweep", src)
        sys.exit(2)
    try:
        shutil.copy2(src, dst)
        # drop any stale journal/wal for the copy
        for ext in ("-journal", "-wal", "-shm"):
            p = dst + ext
            if os.path.exists(p):
                os.remove(p)
    except OSError as e:
        log.error("could not stage reconcile session: %s", e)
        sys.exit(2)


async def run(lookback, dialog_filters, dry_run):
    _ensure_session_copy()
    client = SourceClient(RECONCILE_SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("SESSION NOT AUTHORIZED — collector login required."); sys.exit(2)
    dynmap = build_folder_map()
    try:
        excluded = store_client.get_excluded()
    except Exception as e:  # noqa: BLE001
        log.error("excluded fetch failed: %s — aborting to avoid re-adding trash", e)
        await client.disconnect(); sys.exit(3)
    log.info("reconcile start: lookback=%d folder_meta=%d excluded=%d dry_run=%s",
             lookback, len(dynmap), len(excluded), dry_run)

    seen = set()
    scanned = pushed = skipped = failed = 0
    async for d in client.iter_dialogs():
        if not d.is_user:  # private 1:1 only
            continue
        if dialog_filters and not any(s.lower() in (d.name or "").lower() for s in dialog_filters):
            continue
        cid = str(d.id)
        folder = dynmap.get(cid) or sanitize(d.name)
        async for msg in client.iter_messages(d.entity, limit=lookback):
            if getattr(msg, "out", False):
                continue
            kind = media_kind(msg)
            if not kind:
                continue
            scanned += 1
            stem = f"{d.id}_{msg.id}"
            if stem in seen:
                continue
            seen.add(stem)
            if stem in excluded:
                skipped += 1
                continue
            date_iso = msg.date.isoformat() if msg.date else ""
            if dry_run:
                log.info("WOULD push %s (%s) date=%s -> %s", stem, kind, date_iso, folder)
                pushed += 1
                continue
            tmp = STAGING / stem
            try:
                path = await msg.download_media(file=str(tmp))
                if not path or os.path.getsize(path) == 0:
                    log.warning("empty download %s", stem); continue
                store_client.push_media(folder, path, stem, date_iso, is_out=False)
                pushed += 1
                log.info("PUSHED %s (%s) -> %s", stem, kind, folder)
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.error("push failed %s: %s: %s", stem, type(e).__name__, e)
            finally:
                for p in [str(tmp)] + glob.glob(str(tmp) + "*"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    log.info("reconcile done: scanned=%d pushed=%d skipped_excluded=%d failed=%d",
             scanned, pushed, skipped, failed)
    await client.disconnect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=int(os.environ.get("TG_RECONCILE_LOOKBACK", "40")))
    ap.add_argument("--dialogs", nargs="*", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    asyncio.run(run(a.lookback, a.dialogs, a.dry_run))


if __name__ == "__main__":
    main()
