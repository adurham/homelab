#!/usr/bin/env python3
"""
On-the-fly thumbnail service for the TG gallery.

Serves GET /thumb/<chat>/<stem>.jpg :
  1. if gcrypt:thumbs/<chat>/<stem>.jpg exists -> stream it (cache hit)
  2. else: fetch the original from gcrypt:by-chat/<chat>/<stem>.<ext>,
     generate a ~400px JPEG (Pillow for images, ffmpeg poster for videos),
     upload it to gcrypt:thumbs/<chat>/<stem>.jpg (encrypted, GDrive-backed),
     and return it.

Also a small in-memory + local-disk cache so repeat hits don't round-trip to
Drive. Designed so the gallery NEVER depends on a batch job: missing thumbs are
made on demand, and new captures get thumbnails the first time they're viewed.

Runs as its own service on 127.0.0.1:<port>; nginx/rclone-serve route /thumb/*
here (or the SPA points straight at it via the same vhost). Read-through cache,
no auth (gated by Authentik at lb-01 like the rest).

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:), THUMB_PORT (default 8090),
     THUMB_LOCAL_CACHE (default /var/lib/media-gallery/thumbcache).
"""
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from PIL import Image

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediaingest/.config/rclone/rclone.conf")
PORT = int(os.environ.get("THUMB_PORT", "8090"))
# Bind address: must be reachable by lb-01's nginx (which proxies /thumb/ to
# the CT's private IP), so default to the private IP, NOT 127.0.0.1. Override
# with THUMB_BIND if needed.
BIND = os.environ.get("THUMB_BIND", "172.16.0.46")
LOCAL_CACHE = Path(os.environ.get("THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
THUMB_PX = 400
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}

LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
_locks = {}
_locks_guard = threading.Lock()

# ─── Space-aware admission for original downloads ──────────────────────────
# To thumbnail a VIDEO we download the full original into the (RAM tmpfs) cache,
# so the real constraint is BYTES not a request count: a naive count semaphore
# (e.g. allow 2) can still co-schedule two 3+ GB videos and blow a 6 GB tmpfs.
# Instead admit a download only when (file_size + margin) fits in CURRENT free
# space, reserving the bytes for the duration so concurrent downloads see the
# reduced headroom. A single dedicated big-download lock guarantees forward
# progress (one oversized file at a time always proceeds, never deadlocks).
_space_cv = threading.Condition()
_reserved_bytes = [0]
SPACE_MARGIN = int(os.environ.get("THUMB_SPACE_MARGIN_MB", "256")) * 1024 * 1024
_big_lock = threading.Lock()  # serializes the largest fetches for forward progress


def _free_bytes() -> int:
    try:
        return shutil.disk_usage(str(LOCAL_CACHE)).free - _reserved_bytes[0]
    except OSError:
        return 0


class _SpaceReservation:
    """Block until `need` bytes are reservable in the cache fs, hold the
    reservation, release on exit. If `need` alone exceeds total capacity we
    can't satisfy it — caller should skip (poster not generatable here)."""
    def __init__(self, need):
        self.need = need + SPACE_MARGIN
        self.ok = False

    def __enter__(self):
        try:
            total = shutil.disk_usage(str(LOCAL_CACHE)).total
        except OSError:
            total = 0
        if self.need >= total:
            self.ok = False
            return self  # impossible to ever fit; caller skips
        with _space_cv:
            # wait until our bytes fit alongside existing reservations
            waited = 0
            while _free_bytes() < self.need and waited < 600:
                _space_cv.wait(timeout=5)
                waited += 5
            _reserved_bytes[0] += self.need
            self.ok = True
        return self

    def __exit__(self, *a):
        if self.ok:
            with _space_cv:
                _reserved_bytes[0] -= self.need
                _space_cv.notify_all()


def _lock_for(key):
    with _locks_guard:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


def rclone(*args):
    return subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)


class _NullCtx:
    """No-op context manager (used when a download isn't 'big')."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def remote_size(chat, leaf):
    """Decrypted byte size of an original via `rclone size`, or None if unknown.
    Used to reserve cache space before downloading for a video poster."""
    r = rclone("size", f"{SRC}/{chat}/{leaf}", "--json")
    if r.returncode != 0:
        return None
    try:
        import json
        return int(json.loads(r.stdout).get("bytes"))
    except (ValueError, TypeError, AttributeError):
        return None


def find_original(chat, stem):
    """Return the leaf filename of the original for chat/stem, or None."""
    r = rclone("lsf", f"{SRC}/{chat}/")
    for line in r.stdout.splitlines():
        leaf = line.strip()
        if leaf.startswith(stem + "."):
            return leaf
    return None


def make_thumb(src_path: Path, dst_path: Path, is_video: bool):
    if is_video:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(src_path),
             "-frames:v", "1", "-vf", f"scale={THUMB_PX}:-1", str(dst_path)],
            check=True,
        )
    else:
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX), Image.LANCZOS)
            im.save(dst_path, "JPEG", quality=80)


def ensure_thumb(chat, stem) -> Path | None:
    """Return a local path to the thumb, generating+caching as needed."""
    local = LOCAL_CACHE / chat / f"{stem}.jpg"
    if local.exists() and local.stat().st_size > 0:
        return local
    lk = _lock_for(f"{chat}/{stem}")
    with lk:
        if local.exists() and local.stat().st_size > 0:
            return local
        local.parent.mkdir(parents=True, exist_ok=True)
        # 1) try the encrypted cache on Drive
        r = rclone("copyto", f"{THUMBS}/{chat}/{stem}.jpg", str(local))
        if r.returncode == 0 and local.exists() and local.stat().st_size > 0:
            return local
        # 2) generate from the original
        leaf = find_original(chat, stem)
        if not leaf:
            return None
        ext = os.path.splitext(leaf)[1].lower()
        is_video = ext in VIDEO_EXT
        tmp_src = LOCAL_CACHE / chat / f"_src_{leaf}"
        # Reserve space for the full original BEFORE downloading, so concurrent
        # video requests can't collectively overflow the (RAM tmpfs) cache. The
        # constraint is bytes, not a request count — admit only when the file
        # fits in current free space. If the file is bigger than the cache total,
        # the poster simply can't be generated here (skip, no crash).
        need = remote_size(chat, leaf)
        if need is None:
            need = 0  # unknown size: don't block on reservation, best-effort
        # For the LARGEST files (those that need most of the cache), funnel
        # through _big_lock so two huge fetches never even try to overlap.
        try:
            cache_total = shutil.disk_usage(str(LOCAL_CACHE)).total
        except OSError:
            cache_total = 0
        is_big = cache_total and need > cache_total // 2
        big_ctx = _big_lock if is_big else _NullCtx()
        with big_ctx, _SpaceReservation(need) as res:
            if need and not res.ok:
                # original is larger than the cache fs can ever hold -> can't
                # thumbnail it here. Return None (gallery shows a placeholder).
                return None
            try:
                r = rclone("copyto", f"{SRC}/{chat}/{leaf}", str(tmp_src))
                if r.returncode != 0:
                    return None
                make_thumb(tmp_src, local, is_video)
                # 3) persist to encrypted Drive cache (best effort, async-ish)
                rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                return local if local.exists() else None
            except Exception:  # noqa: BLE001
                return None
            finally:
                try:
                    tmp_src.unlink()
                except OSError:
                    pass


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        # path: /thumb/<chat>/<stem>.jpg
        p = unquote(self.path)
        if not p.startswith("/thumb/"):
            self.send_error(404)
            return
        rest = p[len("/thumb/"):]
        if "/" not in rest or not rest.endswith(".jpg"):
            self.send_error(404)
            return
        chat, fname = rest.split("/", 1)
        stem = fname[:-4]  # strip .jpg
        # basic path-traversal guard
        if ".." in chat or ".." in stem or "/" in stem:
            self.send_error(400)
            return
        thumb = ensure_thumb(chat, stem)
        if not thumb:
            self.send_error(404)
            return
        data = thumb.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)


def main():
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"thumb service on {BIND}:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
