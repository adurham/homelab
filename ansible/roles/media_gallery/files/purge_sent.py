#!/usr/bin/env python3
"""
One-time (re-runnable) purge: remove media YOU sent from the archive, and add
those stems to the exclusion ledger so they never come back.

Scans upstream source for photo/video messages with out=True, intersects with what's
actually stored in gcrypt:by-chat, deletes original + thumb from Drive, and
appends the stems to the ledger (local + Drive-mirrored). Idempotent.

Env: TG_API_ID, TG_API_HASH, TG_SESSION, RCLONE_CONFIG, TG_RCLONE_REMOTE,
     TG_EXCLUDE_FILE.
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from telethon import TelegramClient as SourceClient
from telethon.tl.types import InputMessagesFilterPhotoVideo

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/galmeta")
REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
EXCLUDE_FILE = Path(os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json"))
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
EXCLUDE_REMOTE = REMOTE + "gallery/excluded.json"


def log(*a):
    print(*a, flush=True)


def rclone(*args):
    return subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)


def load_excluded() -> set:
    try:
        return set(json.loads(EXCLUDE_FILE.read_text()))
    except (OSError, ValueError):
        return set()


def save_excluded(s: set):
    EXCLUDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(EXCLUDE_FILE) + ".tmp"
    Path(tmp).write_text(json.dumps(sorted(s)))
    os.replace(tmp, EXCLUDE_FILE)
    rclone("copyto", str(EXCLUDE_FILE), EXCLUDE_REMOTE)


def stored_index():
    """map stem -> (chat, leaf) for everything in by-chat."""
    r = rclone("lsf", "-R", "--files-only", SRC)
    idx = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        chat, leaf = line.split("/", 1)
        if "/" in leaf:
            continue
        stem = os.path.splitext(leaf)[0]
        idx[stem] = (chat, leaf)
    return idx


async def main():
    dry = "--apply" not in sys.argv
    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log("SESSION NOT AUTHORIZED"); sys.exit(2)

    log("Scanning upstream source for OUTGOING photo/video stems...")
    outgoing = set()
    async for d in client.iter_dialogs():
        try:
            async for msg in client.iter_messages(d.entity, filter=InputMessagesFilterPhotoVideo):
                if msg.media and getattr(msg, "out", False):
                    outgoing.add(f"{d.id}_{msg.id}")
        except Exception as e:  # noqa: BLE001
            log(f"  (skip {d.name!r}: {type(e).__name__})")
    await client.disconnect()
    log(f"  outgoing stems in upstream source: {len(outgoing)}")

    idx = stored_index()
    to_purge = [s for s in outgoing if s in idx]
    log(f"  of those, stored in archive: {len(to_purge)}")

    if dry:
        log("DRY RUN (pass --apply to delete). Sample:")
        for s in to_purge[:10]:
            log(f"   would purge {idx[s][0]}/{idx[s][1]}")
        return

    ex = load_excluded()
    deleted = 0
    for stem in to_purge:
        chat, leaf = idx[stem]
        rclone("deletefile", f"{SRC}/{chat}/{leaf}")
        rclone("deletefile", f"{THUMBS}/{chat}/{stem}.jpg")
        ex.add(stem)
        deleted += 1
        if deleted % 25 == 0:
            log(f"   purged {deleted}/{len(to_purge)}")
    save_excluded(ex)
    log(f"PURGED {deleted} outgoing items; excluded ledger now {len(ex)}. "
        f"Re-run build_manifest to refresh the gallery.")


if __name__ == "__main__":
    asyncio.run(main())
