#!/usr/bin/env python3
"""
Fast manifest builder for the TG gallery (NO thumbnails — those are made
on-the-fly by thumb_service.py). Writes gcrypt:gallery/manifest.json in
seconds so the gallery works immediately.

manifest.json: array of items sorted by message date DESC:
  {stem, chat, file, thumb, type, date}
where thumb is the on-the-fly endpoint path /thumb/<chat>/<stem>.jpg.

Resumable/idempotent: just re-run after new captures to refresh the manifest.

Env: TG_API_ID, TG_API_HASH, TG_SESSION, RCLONE_CONFIG, TG_RCLONE_REMOTE.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from telethon import TelegramClient as SourceClient
from telethon.tl.types import InputMessagesFilterPhotoVideo

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/galmeta")
REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
EXCLUDE_FILE = os.environ.get("TG_EXCLUDE_FILE", "/var/lib/media-gallery/excluded.json")
SRC = REMOTE + "by-chat"
GALLERY = REMOTE + "gallery"


def load_excluded() -> set:
    """Stems the user trashed — skip them in the manifest so they don't show."""
    try:
        import json as _j
        with open(EXCLUDE_FILE) as f:
            return set(_j.load(f))
    except (OSError, ValueError):
        return set()

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}

CHAT_NAMES = {
    "100000001": "person1",
    "100000002": "person2",
    "100000003": "person3",
    "100000004": "person4",
    "100000005": "person5",
    "777000": "upstream source",
}


def log(*a):
    print(*a, flush=True)


def rclone(*args):
    return subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


def chat_folder_for(chat_id, name):
    return CHAT_NAMES.get(str(chat_id), sanitize(name))


async def date_map(client):
    """stem -> {date, out}. 'out' True = message YOU sent (filtered out of the
    gallery — we only keep media sent TO you)."""
    m = {}
    async for d in client.iter_dialogs():
        try:
            async for msg in client.iter_messages(d.entity, filter=InputMessagesFilterPhotoVideo):
                if msg.media:
                    m[f"{d.id}_{msg.id}"] = {
                        "date": msg.date.isoformat() if msg.date else None,
                        "out": bool(getattr(msg, "out", False)),
                    }
        except Exception as e:  # noqa: BLE001
            log(f"  (skip {d.name!r}: {type(e).__name__})")
    return m


def list_originals():
    r = rclone("lsf", "-R", "--files-only", SRC)
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        chat, leaf = line.split("/", 1)
        if "/" in leaf:  # skip nested unexpectedly
            continue
        stem, ext = os.path.splitext(leaf)
        out.append((chat, leaf, stem, ext.lower()))
    return out


async def main():
    client = SourceClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log("SESSION NOT AUTHORIZED"); sys.exit(2)
    log("Scanning upstream source for message dates...")
    dates = await date_map(client)
    await client.disconnect()
    log(f"  date map: {len(dates)} items")

    originals = list_originals()
    log(f"originals: {len(originals)}")

    excluded = load_excluded()
    log(f"excluded (trashed): {len(excluded)}")

    manifest = []
    skipped_excluded = skipped_outgoing = 0
    for chat, leaf, stem, ext in originals:
        is_video = ext in VIDEO_EXT
        if not (is_video or ext in IMAGE_EXT):
            continue
        if stem in excluded:
            skipped_excluded += 1
            continue
        meta = dates.get(stem) or {}
        if meta.get("out"):  # message YOU sent — keep only received media
            skipped_outgoing += 1
            continue
        manifest.append({
            "stem": stem,
            "chat": chat,
            "file": f"by-chat/{chat}/{leaf}",
            "thumb": f"thumb/{chat}/{stem}.jpg",  # on-the-fly endpoint
            "type": "video" if is_video else "image",
            "date": meta.get("date"),
        })
    manifest.sort(key=lambda x: (x["date"] or ""), reverse=True)
    log(f"manifest items: {len(manifest)} (skipped {skipped_excluded} trashed, "
        f"{skipped_outgoing} outgoing)")

    work = Path(tempfile.mkdtemp(prefix="manifest_"))
    mp = work / "manifest.json"
    mp.write_text(json.dumps(manifest, separators=(",", ":")))
    rclone("copyto", str(mp), f"{GALLERY}/manifest.json")
    mp.unlink()
    log("manifest uploaded to gcrypt:gallery/manifest.json — DONE")


if __name__ == "__main__":
    asyncio.run(main())
