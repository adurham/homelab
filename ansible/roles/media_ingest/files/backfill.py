#!/usr/bin/env python3
"""
Backfill (collector edition) — walk upstream source history and PUSH photos/videos to the
gallery via the authenticated ingest API. Streaming + resumable + throttled.
No rclone/crypt here; the gallery encrypts + stores.

For each dialog, oldest->newest from the per-dialog checkpoint:
  - skip msg.out=True (only media sent TO us)
  - skip stems in the gallery's exclusion ledger (trashed/purged — don't re-add)
  - download to tmpfs staging, push_media(folder, path, stem, date, out=False),
    delete local. Checkpoint the max msg id seen.

Env: TG_API_ID, TG_API_HASH, TG_SESSION, plus store_client env. Flags:
  --dialogs <substr...>   restrict to dialog name substrings
  --sleep S               inter-item pause (default 0.1)
  --count                 enumerate only (per-chat photo/video totals)
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient as SourceClient
from telethon.tl.types import InputMessagesFilterPhotoVideo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store_client  # noqa: E402

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-ingest/backfill")
STAGING = Path(os.environ.get("TG_STAGING", "/var/lib/media-ingest/staging"))
STATE_FILE = os.environ.get("TG_BACKFILL_STATE", "/var/lib/media-ingest/backfill_state.json")

CHAT_NAMES = {
    "100000001": "person1", "100000002": "person2", "100000003": "person3",
    "100000004": "person4", "100000005": "person5", "777000": "upstream source",
}
STAGING.mkdir(parents=True, exist_ok=True)


def log(*a):
    print(*a, flush=True)


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


def folder_for(cid, name):
    return CHAT_NAMES.get(str(cid), sanitize(name))


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_FILE)


async def do_count(client, filters):
    grand = 0
    async for d in client.iter_dialogs():
        if filters and not any(f.lower() in (d.name or "").lower() for f in filters):
            continue
        try:
            res = await client.get_messages(d.entity, limit=0, filter=InputMessagesFilterPhotoVideo)
        except Exception:  # noqa: BLE001
            continue
        if res.total:
            log(f"  {res.total:6d}  {d.name}")
            grand += res.total
    log(f"GRAND TOTAL: {grand}")


async def do_run(client, filters, sleep_s):
    state = load_state()
    excluded = store_client.get_excluded()
    log(f"excluded (skip): {len(excluded)}")
    pushed = 0
    async for d in client.iter_dialogs():
        if filters and not any(f.lower() in (d.name or "").lower() for f in filters):
            continue
        cid = d.id
        folder = folder_for(cid, d.name)
        key = str(cid)
        last = state.get(key, 0)
        maxseen = last
        log(f"--- {d.name!r} -> {folder} (resume after {last}) ---")
        try:
            async for msg in client.iter_messages(d.entity, filter=InputMessagesFilterPhotoVideo,
                                                   min_id=last, reverse=True):
                if not msg.media:
                    continue
                maxseen = max(maxseen, msg.id)
                if getattr(msg, "out", False):
                    continue
                stem = f"{cid}_{msg.id}"
                if stem in excluded:
                    continue
                tmp = STAGING / stem
                try:
                    path = await msg.download_media(file=str(tmp))
                    if path and os.path.getsize(path) > 0:
                        date_iso = msg.date.isoformat() if msg.date else ""
                        store_client.push_media(folder, path, stem, date_iso, is_out=False)
                        pushed += 1
                        if pushed % 25 == 0:
                            log(f"   pushed {pushed}; checkpoint {folder}@{maxseen}")
                            state[key] = maxseen; save_state(state)
                except Exception as e:  # noqa: BLE001
                    log(f"   fail {stem}: {type(e).__name__}: {e}")
                finally:
                    for p in STAGING.glob(stem + "*"):
                        try:
                            p.unlink()
                        except OSError:
                            pass
                if sleep_s:
                    await asyncio.sleep(sleep_s)
        except Exception as e:  # noqa: BLE001
            log(f"   chat error {d.name!r}: {type(e).__name__}: {e}")
        state[key] = maxseen
        save_state(state)
    log(f"BACKFILL COMPLETE. pushed this run: {pushed}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--dialogs", nargs="*", default=[])
    ap.add_argument("--sleep", type=float, default=0.1)
    args = ap.parse_args()
    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log("SESSION NOT AUTHORIZED"); sys.exit(2)
    if args.count:
        await do_count(client, args.dialogs)
    else:
        await do_run(client, args.dialogs, args.sleep)
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
