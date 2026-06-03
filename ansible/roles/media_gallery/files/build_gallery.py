#!/usr/bin/env python3
"""
Build a pre-rendered, encrypted, date-sorted gallery for the TG archive.

Pipeline (all derived assets are ENCRYPTED via the crypt remote and land in
Google Drive for backup; local disk is only a transient work area):

  1. Pull message metadata (date + type) from upstream source for every photo/video,
     keyed by stem "<chat_id>_<msg_id>". Downloads nothing — just .date.
  2. Enumerate originals in gcrypt:by-chat/<Chat>/<stem>.<ext>.
  3. For each original NOT already thumbnailed: download it to a temp dir,
     generate a ~400px JPEG thumbnail (Pillow for images; ffmpeg poster frame
     for videos), upload the thumb to gcrypt:thumbs/<Chat>/<stem>.jpg, delete
     local temp. Streaming so the 8GB disk never fills.
  4. Emit manifest.json (sorted by message date DESC) listing every item:
     {stem, chat, file, thumb, type, date, w, h}. Upload to gcrypt:gallery/.
  5. Upload the gallery SPA (index.html) to gcrypt:gallery/.

Resumable: skips items whose thumb already exists in gcrypt:thumbs. Safe to
re-run after new captures land.

Env: TG_API_ID, TG_API_HASH, TG_SESSION, RCLONE_CONFIG, plus
     TG_RCLONE_REMOTE (default gcrypt:).
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
from PIL import Image

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ.get("TG_SESSION", "/var/lib/media-gallery/galmeta")
REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
GALLERY = REMOTE + "gallery"

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
THUMB_PX = 400


def log(*a):
    print(*a, flush=True)


def rclone(*args, capture=True):
    cmd = ["rclone", "--config", RCLONE_CONF, *args]
    return subprocess.run(cmd, capture_output=capture, text=True)


# Stable chat-id -> folder name map (matches the actual gcrypt:by-chat layout).
# Needed because some chats have emoji-only names that sanitize to empty; we
# pin them here so the manifest's thumb/file paths line up with the folders.
CHAT_NAMES = {
    "100000001": "person1",
    "100000002": "person2",
    "100000003": "person3",
    "100000004": "person4",        # ❤️ emoji chat
    "100000005": "person5",
    "777000": "upstream source",         # service messages
}


def sanitize(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in (name or "")).strip()
    return keep.replace(" ", "-") or "unknown"


def chat_folder_for(chat_id, name):
    """Resolve the on-disk folder name for a chat id, preferring the pinned map."""
    return CHAT_NAMES.get(str(chat_id), sanitize(name))


async def date_map(client):
    """stem -> {date(iso), type, chat} for every photo/video in all dialogs."""
    m = {}
    async for d in client.iter_dialogs():
        chat = chat_folder_for(d.id, d.name)
        try:
            async for msg in client.iter_messages(d.entity, filter=InputMessagesFilterPhotoVideo):
                if not msg.media:
                    continue
                stem = f"{d.id}_{msg.id}"
                m[stem] = {
                    "date": msg.date.isoformat() if msg.date else None,
                    "chat": chat,
                }
        except Exception as e:  # noqa: BLE001
            log(f"  (date scan skip {d.name!r}: {type(e).__name__})")
    return m


def list_originals():
    """Return list of (chat, leaf, stem, ext) for everything in by-chat."""
    r = rclone("lsf", "-R", "--files-only", SRC)
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        chat, leaf = line.split("/", 1)
        stem, ext = os.path.splitext(leaf)
        out.append((chat, leaf, stem, ext.lower()))
    return out


def existing_thumbs():
    r = rclone("lsf", "-R", "--files-only", THUMBS)
    return set(line.strip() for line in r.stdout.splitlines() if line.strip())


def make_image_thumb(src_path, dst_path):
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        im.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
        im.save(dst_path, "JPEG", quality=80)
        return w, h


def make_video_thumb(src_path, dst_path):
    # grab a frame ~1s in, scale to THUMB_PX wide
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(src_path),
         "-frames:v", "1", "-vf", f"scale={THUMB_PX}:-1", str(dst_path)],
        check=True,
    )
    # probe original dims
    try:
        pr = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(src_path)],
            capture_output=True, text=True, check=True,
        )
        w, h = (int(x) for x in pr.stdout.strip().split("x")[:2])
        return w, h
    except Exception:  # noqa: BLE001
        return 0, 0


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
    log(f"originals in by-chat: {len(originals)}")
    have = existing_thumbs()
    log(f"existing thumbs: {len(have)}")

    manifest = []
    work = Path(tempfile.mkdtemp(prefix="galbuild_"))
    made = 0
    for chat, leaf, stem, ext in originals:
        is_video = ext in VIDEO_EXT
        is_image = ext in IMAGE_EXT
        if not (is_video or is_image):
            continue
        thumb_rel = f"{chat}/{stem}.jpg"
        meta = dates.get(stem, {})
        item = {
            "stem": stem,
            "chat": chat,
            "file": f"by-chat/{chat}/{leaf}",
            "thumb": f"thumbs/{thumb_rel}",
            "type": "video" if is_video else "image",
            "date": meta.get("date"),
        }

        if thumb_rel not in have:
            local_src = work / leaf.replace("/", "_")
            local_thumb = work / f"{stem}.jpg"
            try:
                rclone("copyto", f"{SRC}/{chat}/{leaf}", str(local_src), capture=True)
                if is_video:
                    w, h = make_video_thumb(local_src, local_thumb)
                else:
                    w, h = make_image_thumb(local_src, local_thumb)
                item["w"], item["h"] = w, h
                rclone("copyto", str(local_thumb), f"{THUMBS}/{thumb_rel}", capture=True)
                made += 1
                if made % 25 == 0:
                    log(f"  thumbs made: {made}")
            except Exception as e:  # noqa: BLE001
                log(f"  thumb fail {stem}: {type(e).__name__}: {e}")
            finally:
                for p in (local_src, local_thumb):
                    try:
                        p.unlink()
                    except OSError:
                        pass
        manifest.append(item)

    # sort by date desc (None dates sink to bottom)
    manifest.sort(key=lambda x: (x["date"] or ""), reverse=True)
    log(f"manifest items: {len(manifest)}; new thumbs this run: {made}")

    mpath = work / "manifest.json"
    mpath.write_text(json.dumps(manifest, separators=(",", ":")))
    rclone("copyto", str(mpath), f"{GALLERY}/manifest.json", capture=True)
    mpath.unlink()

    # index.html shipped alongside (deployed separately by ansible, but also
    # push here so a standalone run is self-contained if present locally)
    idx = Path(__file__).with_name("gallery_index.html")
    if idx.exists():
        rclone("copyto", str(idx), f"{GALLERY}/index.html", capture=True)
        log("uploaded index.html")

    log("DONE")


if __name__ == "__main__":
    asyncio.run(main())
