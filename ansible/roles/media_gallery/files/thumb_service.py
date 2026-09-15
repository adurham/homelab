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
import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from PIL import Image

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
PORT = int(os.environ.get("THUMB_PORT", "8090"))
# Bind address: must be reachable by lb-01's nginx (which proxies /thumb/ to
# the CT's private IP), so default to the private IP, NOT 127.0.0.1. Override
# with THUMB_BIND if needed.
BIND = os.environ.get("THUMB_BIND", "172.16.0.46")
LOCAL_CACHE = Path(os.environ.get("THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
GALLERY = REMOTE + "gallery"
THUMB_PX = 400
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}
# Bytes of a video to stream for a poster frame (header + first frames) instead
# of downloading the whole original. 24 MiB covers most start-of-file moov atoms.
VIDEO_HEAD_BYTES = int(os.environ.get("THUMB_VIDEO_HEAD_BYTES", str(24 * 1024 * 1024)))
# Above this size we never full-download just for a poster (placeholder instead).
VIDEO_FULL_MAX = int(os.environ.get("THUMB_VIDEO_FULL_MAX_MB", "300")) * 1024 * 1024

LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
_locks = {}
_locks_guard = threading.Lock()

# ─── manifest-backed filename index (see find_original's docstring) ────────
# Avoids the expensive per-request full-folder `rclone lsf` by reusing the
# leaf filename build_manifest.py already recorded for every item. Refreshed
# lazily (max once per MANIFEST_INDEX_TTL_SEC) rather than on every request,
# so a burst of requests for the same still-warm index costs nothing extra;
# refreshed from build_manifest.py's OWN output cadence (hourly refresh), so
# TTL only needs to be "don't refetch a 60+ MB file on every single request",
# not "must be perfectly real-time" -- a small staleness window here just
# means occasionally falling through to the (correct, just slower) full
# listing for a handful of very recently ingested items, never wrong data.
MANIFEST_INDEX_TTL_SEC = int(os.environ.get("THUMB_MANIFEST_INDEX_TTL_SEC", "300"))
_manifest_index_cache = {"index": {}, "built_at": 0.0}
_manifest_index_lock = threading.Lock()


def _build_manifest_index():
    """Fetch manifest.json fresh and return (index, ok) where index is
    {"<chat>/<stem>": leaf_filename} and ok is False only on a genuine fetch/
    parse failure (never on a successfully-fetched-but-empty manifest, which
    is a real possible state and must still update built_at so a stream of
    misses doesn't refetch on every single request within the TTL window).
    Best-effort: returns ({}, False) on any failure so callers always fall
    through to the real folder listing rather than ever raising out of a
    live request path."""
    tmp = LOCAL_CACHE / "_manifest_index_fetch.json"
    try:
        r = rclone("copyto", f"{GALLERY}/manifest.json", str(tmp))
        if r.returncode != 0:
            print(f"[thumb] manifest fetch for index failed: {r.stderr[:200]!r}", flush=True)
            return {}, False
        manifest = json.loads(tmp.read_text())
        index = {}
        for it in manifest:
            chat = it.get("chat") or ""
            stem = it.get("stem")
            fpath = it.get("file") or ""
            if not stem or not fpath:
                continue
            index[f"{chat}/{stem}"] = os.path.basename(fpath)
        return index, True
    except Exception as e:  # noqa: BLE001 — index building must never crash the service
        print(f"[thumb] manifest index build failed: {type(e).__name__}: {e}", flush=True)
        return {}, False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _manifest_index() -> dict:
    """Return the cached {"<chat>/<stem>": leaf} index, rebuilding it if
    older than MANIFEST_INDEX_TTL_SEC. Thread-safe; a rebuild-in-progress
    briefly serves the previous (still-correct, just slightly stale) index
    to any other thread rather than blocking every concurrent request on
    the same fetch."""
    now = time.time()
    with _manifest_index_lock:
        stale = (now - _manifest_index_cache["built_at"]) > MANIFEST_INDEX_TTL_SEC
        building_now = stale and not _manifest_index_cache.get("_building")
        if building_now:
            _manifest_index_cache["_building"] = True
    if building_now:
        try:
            fresh, ok = _build_manifest_index()
            with _manifest_index_lock:
                if ok:  # only a genuine fetch failure skips the update; an
                    # empty-but-successfully-fetched manifest is a real state
                    # and must still refresh built_at (see docstring above).
                    _manifest_index_cache["index"] = fresh
                    _manifest_index_cache["built_at"] = now
        finally:
            with _manifest_index_lock:
                _manifest_index_cache["_building"] = False
    return _manifest_index_cache["index"]


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
    """Return the leaf filename of the original for chat/stem, or None.

    PERFORMANCE FIX (2026-09-15): this used to ALWAYS do a full `rclone lsf`
    of the entire chat folder to find one filename by prefix-matching the
    stem. Measured live against gallery-01's real Drive-backed crypt remote:
    23s for a 7249-item folder, and worse, a TARGETED single-file `rclone
    size`/`lsf` on the exact same file was JUST AS SLOW (~16s) -- Google
    Drive's API needs a directory-level query either way here, so there is
    no cheap per-file existence check available on this remote. That means
    this cost was being paid on every live page-view that hit an uncached
    thumbnail for ANY item in a large folder, not just during the batch
    backfill (thumb_backfill.py, fixed separately, has its own fast path
    that bypasses find_original entirely using the manifest's exact leaf
    filename -- see that file's PERFORMANCE FIX docstring).

    Since a real per-request check is exactly as expensive as the thing
    it's supposedly avoiding, the only way to make this fast is to NOT ask
    Drive at request time at all: build_manifest.py already lists every
    chat folder once per hourly refresh and records each item's real leaf
    filename in manifest.json's "file" field. This looks that up locally
    (an in-memory index cache, refreshed lazily -- see _manifest_index())
    and only falls through to the old full-listing behavior if the index has
    no entry (item not yet in the last-built manifest) OR ensure_thumb's
    caller finds the indexed filename doesn't actually exist on Drive
    (index stale -- e.g. a merge/rename happened since the last manifest
    build). That fallback path is the ONLY place the original full-listing
    cost can still occur, and only for the rare item that's either brand
    new or was just renamed -- not on every request the way it was before.
    """
    leaf = _manifest_index().get(f"{chat}/{stem}")
    if leaf is not None:
        return leaf
    # Fallback: not in the manifest index (too new, or a stale/never-refreshed
    # index) -- do the real (expensive) folder listing, exactly as before.
    r = rclone("lsf", f"{SRC}/{chat}/")
    for line in r.stdout.splitlines():
        candidate = line.strip()
        if candidate.startswith(stem + "."):
            return candidate
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

        # VIDEO posters: don't download the whole original (could be GBs). A frame
        # near the start only needs the file header + first frames, so stream just
        # the first VIDEO_HEAD_BYTES via `rclone cat --count` and let ffmpeg grab a
        # poster from that prefix. Falls back to the full-download path only if the
        # prefix doesn't yield a frame (rare: moov atom at end of file).
        if is_video:
            total = remote_size(chat, leaf) or 0
            # Stream just the first VIDEO_HEAD_BYTES (header + first frames) and let
            # ffmpeg grab a poster from that prefix. Works for faststart/web videos
            # (the vast majority). Avoids pulling the whole original (could be GBs).
            part = LOCAL_CACHE / chat / f"_part_{leaf}"
            part.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(part, "wb") as fh:
                    cp = subprocess.run(
                        ["rclone", "--config", RCLONE_CONF, "cat",
                         "--count", str(VIDEO_HEAD_BYTES), f"{SRC}/{chat}/{leaf}"],
                        stdout=fh, stderr=subprocess.DEVNULL, timeout=120,
                    )
                if cp.returncode == 0 and part.exists() and part.stat().st_size > 0:
                    make_thumb(part, local, True)
                    if local.exists() and local.stat().st_size > 0:
                        rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                        return local
            except Exception as e:  # noqa: BLE001
                print(f"[thumb] prefix frame decode failed for {chat}/{stem}: {e}", flush=True)
                # prefix had no decodable frame (e.g. trailing moov) -> below
            finally:
                try:
                    part.unlink()
                except OSError:
                    pass
            # prefix failed. For very large videos, DON'T full-download just for a
            # poster — show a placeholder instead (avoids the 1.4 GB-for-a-thumb
            # stall that hammered Drive). Smaller videos fall through to full DL.
            if total and total > VIDEO_FULL_MAX:
                return None
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
                if r.returncode != 0 and "directory not found" in (r.stderr or ""):
                    # The manifest-index leaf doesn't actually exist on Drive
                    # anymore (stale index -- e.g. a folder merge/rename since
                    # the last manifest build; see find_original's docstring).
                    # Retry ONCE with the authoritative full listing before
                    # giving up -- this is the deliberate, rare-path fallback
                    # cost, not something paid on every request.
                    fresh_r = rclone("lsf", f"{SRC}/{chat}/")
                    fresh_leaf = next(
                        (c.strip() for c in fresh_r.stdout.splitlines()
                         if c.strip().startswith(stem + ".")), None)
                    if fresh_leaf and fresh_leaf != leaf:
                        print(f"[thumb] stale manifest-index entry for {chat}/{stem} "
                              f"({leaf!r} -> {fresh_leaf!r}), retrying with real listing",
                              flush=True)
                        leaf = fresh_leaf
                        r = rclone("copyto", f"{SRC}/{chat}/{leaf}", str(tmp_src))
                if r.returncode != 0:
                    print(f"[thumb] download original failed {chat}/{leaf}: "
                          f"rc={r.returncode} stderr={r.stderr[:300]!r}", flush=True)
                    return None
                make_thumb(tmp_src, local, is_video)
                # 3) persist to encrypted Drive cache (best effort, async-ish)
                rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                return local if local.exists() else None
            except Exception as e:  # noqa: BLE001
                # 2026-09-12: this used to swallow every failure silently
                # (bare `return None`, zero output) -- a real incident (a
                # root-owned, 0600 rclone.conf this service user couldn't
                # read) caused every rclone subprocess spawned from here to
                # fail with EACCES, and NOTHING was logged anywhere for the
                # ~2 hours it took to notice, because this branch ate the
                # exception with no trace. Always log what actually failed;
                # a thumb genuinely not being generatable is a normal,
                # occasional outcome (return None is still correct), but it
                # must never be indistinguishable from a real bug like this.
                print(f"[thumb] generation failed {chat}/{stem}: "
                      f"{type(e).__name__}: {e}", flush=True)
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
