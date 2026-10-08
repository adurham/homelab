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

from PIL import Image, ImageFile

from serve_publish import local_path as serve_local_path

# Truncated-but-viewable JPEGs: the source platforms (and the scrapers that
# copy from them) occasionally store files cut short by a handful of bytes.
# Browsers render these fine; Pillow refuses them by default, which left
# those items permanently poster-less and looking like a broken thumbnailer.
# Tolerate the truncation (the decode still yields the real image content).
ImageFile.LOAD_TRUNCATED_IMAGES = True

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
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
# Some stems have MULTIPLE siblings on Drive (e.g. scraper sources keep both a
# raw ".bin" download and the real ".mp4"). Plain listing order puts ".bin"
# first alphabetically, so any leaf resolution that just takes the first
# prefix-match picks the wrong file — which then fails to decode and leaves
# that item without a thumbnail forever. Prefer known media extensions.
_PREFERRED_EXT = VIDEO_EXT | IMAGE_EXT
# Where the local rclone serve exposes the archive over HTTP (read-only, same
# instance the browser uses for originals). VIDEO POSTERS ARE MADE FROM THIS
# via ffmpeg's HTTP range support rather than by downloading the file:
# ffmpeg seeks to -ss and pulls ONLY the byte ranges it needs (moov atom +
# the frame near the seek point), so a multi-GB video costs a few MB of
# transfer instead of the full download. Measured on gallery-01: a 4.7 GB
# video (moov at end) produced a poster in ~4 s / few MB. This replaced a
# "download the first 24 MiB and hope the moov atom is in it" trick, which
# fails for every non-faststart file (Telegram/most-camera mp4s put moov at
# the END) and left ~half the library with no video poster at all.
VIDEO_HTTP_BASE = os.environ.get("THUMB_VIDEO_HTTP_BASE", "http://172.16.0.46:8089")
# Fallback ceiling for the legacy full-download path (only used when the
# HTTP route is unavailable/fails — e.g. rclone serve down).
VIDEO_FULL_MAX = int(os.environ.get("THUMB_VIDEO_FULL_MAX_MB", "300")) * 1024 * 1024

LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
_locks = {}
_locks_guard = threading.Lock()

# ─── Negative cache for DETERMINISTIC generation failures (2026-10-08) ──────
# Some stored media can never produce a poster: protected/encrypted source
# video that ffmpeg cannot decode, or files larger than the cache filesystem
# can ever hold. Retrying those costs a full cold generation attempt on EVERY
# view (measured ~25s of ffmpeg per item) — and the batch backfill was
# re-attempting the same ~360 permanently-dead stems twice a minute, burning
# ~90% of its budget forever. A stem whose generation has DETERMINISTICALLY
# failed is remembered here for NEG_TTL and fast-fails instead. Only
# deterministic outcomes are recorded — a Drive fetch failure, a dropped
# connection, or a restarted service is TRANSIENT and must never be cached,
# or a temporary outage would blank real thumbnails for hours. The TTL (not
# permanence) is deliberate: a re-ingested item can legitimately become
# generatable later, and the backfill's retry pass relies on the entry
# expiring. Entries are also cleared explicitly whenever generation succeeds.
_neg = {}
_neg_lock = threading.Lock()
NEG_TTL = float(os.environ.get("THUMB_NEG_TTL_SEC", "21600"))  # 6h
NEG_MAX = int(os.environ.get("THUMB_NEG_MAX", "50000"))


def _neg_failed(chat: str, stem: str) -> bool:
    """True iff this stem's generation failed DETERMINISTICALLY within NEG_TTL.
    Pure read (no pruning) so it is safe to call on every request path."""
    with _neg_lock:
        ts = _neg.get(f"{chat}/{stem}")
    return ts is not None and (time.time() - ts) < NEG_TTL


def _neg_mark(chat: str, stem: str) -> None:
    key = f"{chat}/{stem}"
    now = time.time()
    with _neg_lock:
        if len(_neg) >= NEG_MAX:
            # prune expired, then (if still full) drop the oldest entries
            for k in [k for k, v in _neg.items() if now - v >= NEG_TTL]:
                _neg.pop(k, None)
            if len(_neg) >= NEG_MAX:
                for k, _ in sorted(_neg.items(), key=lambda kv: kv[1])[: NEG_MAX // 4]:
                    _neg.pop(k, None)
        _neg[key] = now


def _neg_clear(chat: str, stem: str) -> None:
    with _neg_lock:
        _neg.pop(f"{chat}/{stem}", None)


# Per-request failure classification. thumb_service is a ThreadingHTTPServer,
# so one thread handles one request end-to-end: a threading.local set by
# ensure_thumb is visible to the Handler right after the call returns, letting
# the 404 response carry WHY generation failed. Batch consumers (the backfill)
# use that to decide whether a failure is worth remembering (deterministic
# decode-level verdict) or must be retried later (transient transport). Values:
# "deterministic" | "transient" | None (never attempted).
_gen_reason = threading.local()


def _set_reason(reason: str) -> None:
    _gen_reason.value = reason

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
        # Prefer the local tmpfs serve copy of the manifest (written by
        # build_manifest.py at every rebuild): reading it costs no Drive
        # traffic, versus the ~85MB copyto this used to do every TTL window.
        local = serve_local_path("manifest.json")
        try:
            if local.is_file():
                manifest = json.loads(local.read_text())
            else:
                manifest = None
        except (OSError, ValueError):
            manifest = None
        if manifest is None:
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
    # index) -- do the real (expensive) folder listing, exactly as before,
    # but prefer a decodable media extension (see _prefer_media_leaf).
    r = rclone("lsf", f"{SRC}/{chat}/")
    return _prefer_media_leaf(r.stdout.splitlines(), stem)


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


_POSTER_TRANSIENT_MARKERS = (
    "connection refused", "timed out", "timeout", "server returned 4",
    "server returned 5", "network", "no route", "temporary failure",
    "could not resolve",
)
# Markers that prove ffmpeg actually READ input bytes and rejected them —
# a decode-level verdict that will not change on retry (typically protected/
# encrypted source media the platform never served as decodable video).
_POSTER_DECODE_MARKERS = (
    "moov atom not found", "invalid data found when processing input",
    "decode_slice_header", "encryption info", "not allocated",
    "prediction is not allowed", "get_buffer() failed", "error while decoding",
    "header missing", "no frame", "decoding error",
)


def _poster_err_is_deterministic(err: str) -> bool:
    low = (err or "").lower()
    if any(m in low for m in _POSTER_TRANSIENT_MARKERS):
        return False
    return any(m in low for m in _POSTER_DECODE_MARKERS)


def _exc_is_deterministic(e: BaseException) -> bool:
    """Classify an exception raised while generating a thumbnail from a
    SUCCESSFULLY downloaded original. A decode-level rejection (ffmpeg says
    the container/codec is unreadable; Pillow says the bytes are not an
    image) is deterministic — retrying will fail identically, so it is worth
    remembering. Anything else (rclone transport, OSError, permissions) is
    transient and must never be cached."""
    if isinstance(e, subprocess.CalledProcessError):
        err = (e.stderr or b"")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return _poster_err_is_deterministic(str(err)) or not err
    # Pillow raises UnidentifiedImageError (OSError subclass) for undecodable
    # bytes; a bare OSError from PIL is likewise a decode verdict here.
    try:
        from PIL import UnidentifiedImageError
        if isinstance(e, UnidentifiedImageError):
            return True
    except ImportError:
        pass
    if type(e).__name__ in ("UnidentifiedImageError", "SyntaxError"):
        return True
    return False


def _video_poster_http(chat: str, leaf: str, dst: Path, class_out: dict | None = None) -> bool:
    """Generate a video poster via ffmpeg against the local rclone HTTP serve.

    Returns True when dst was written. ffmpeg issues HTTP range requests, so
    only the moov atom + the frame near the seek point cross the wire — a few
    MB even for a multi-GB file. `-ss 0` is the second attempt because some
    clips show a blank first frame at 1s; probesize/analyzeduration caps keep
    ffmpeg from scanning deep into the file before decoding.

    class_out (optional): a dict the caller supplies; on a FAILED generation
    it receives class_out["deterministic"]=True/False so the caller can decide
    whether the failure is worth remembering in the negative cache (see
    _neg_mark: only decode-level failures where bytes were actually read are
    deterministic; transport trouble is transient and must never be cached)."""
    url = f"{VIDEO_HTTP_BASE}/by-chat/{chat}/{leaf}"
    last_err = ""
    for seek in ("1", "0"):
        try:
            cp = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-probesize", "5M", "-analyzeduration", "5M",
                 "-ss", seek, "-i", url,
                 "-frames:v", "1", "-vf", f"scale={THUMB_PX}:-1", str(dst)],
                capture_output=True, timeout=120)
            if cp.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
                return True
            last_err = (cp.stderr or b"")[-300:].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            last_err = "timeout"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
    print(f"[thumb] http video poster failed {chat}/{leaf}: {last_err}", flush=True)
    if class_out is not None:
        class_out["deterministic"] = _poster_err_is_deterministic(last_err)
    return False


def _prefer_media_leaf(candidates, stem: str):
    """Pick the best leaf for a stem from listing lines: a known media
    extension wins over anything else (a .bin sibling sorts first in a plain
    listing but cannot be decoded — see _PREFERRED_EXT)."""
    leaves = [c.strip() for c in candidates
              if c.strip().startswith(stem + ".")]
    if not leaves:
        return None
    for leaf in leaves:
        if os.path.splitext(leaf)[1].lower() in _PREFERRED_EXT:
            return leaf
    return leaves[0]


def _refresh_leaf(chat: str, stem: str, stale_leaf: str, log_prefix: str):
    """Authoritative re-resolve of a stem's leaf filename after a stale-index
    404 (folder merge/rename since the last manifest build). Returns the
    corrected leaf or None. Same one-shot full listing the legacy path used,
    with media-extension preference (see _prefer_media_leaf)."""
    fresh_r = rclone("lsf", f"{SRC}/{chat}/")
    fresh_leaf = _prefer_media_leaf(fresh_r.stdout.splitlines(), stem)
    if fresh_leaf and fresh_leaf != stale_leaf:
        print(f"[thumb] {log_prefix} {chat}/{stem} "
              f"({stale_leaf!r} -> {fresh_leaf!r}), retrying with real listing",
              flush=True)
        return fresh_leaf
    return None


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
        # 1b) deterministic-failure fast path: if this exact stem's generation
        # already failed for a reason that cannot change (see _neg_failed),
        # skip the expensive generation attempt. Deliberately AFTER the Drive
        # cache check above, so a thumb that appeared since the failure (e.g.
        # the backfill generated it) is still served.
        if _neg_failed(chat, stem):
            _set_reason("deterministic")
            return None
        # 2) generate from the original
        leaf = find_original(chat, stem)
        if not leaf:
            _set_reason("transient")   # listing miss/failure: retry later
            return None
        ext = os.path.splitext(leaf)[1].lower()
        is_video = ext in VIDEO_EXT
        tmp_src = LOCAL_CACHE / chat / f"_src_{leaf}"

        # VIDEO posters: generate via ffmpeg against the LOCAL rclone HTTP
        # endpoint, which understands range requests — ffmpeg pulls only the
        # moov atom + the frame near the seek point (a few MB even for a
        # multi-GB file). Proven on gallery-01: 4.7 GB video → poster in ~4 s.
        # (`-ss 0` second attempt covers clips whose first second is a
        # blank/black frame; some also need no seek at all.)
        if is_video:
            # attempt 1: manifest's leaf; attempt 2: re-resolved leaf (a stale
            # manifest entry 404s the HTTP fetch just like it did the legacy
            # download — e.g. folder merged/renamed since the last rebuild).
            cls = {}
            if _video_poster_http(chat, leaf, local, class_out=cls):
                rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                _neg_clear(chat, stem)
                return local
            fresh_leaf = _refresh_leaf(chat, stem, leaf, "stale manifest-index entry for")
            if fresh_leaf:
                leaf = fresh_leaf
                if _video_poster_http(chat, leaf, local, class_out=cls):
                    rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                    _neg_clear(chat, stem)
                    return local
            # HTTP route failed (codec ffmpeg can't read? rclone serve down?).
            # Fall through to the legacy full-download path, which still
            # refuses huge files. If the failure was a decode-level verdict
            # (not transport trouble), the fallthrough below can still clear
            # it — but if it also declines, the stem is remembered as dead.
            total = remote_size(chat, leaf) or 0
            if total and total > VIDEO_FULL_MAX:
                if cls.get("deterministic"):
                    _neg_mark(chat, stem)
                    _set_reason("deterministic")
                else:
                    _set_reason("transient")
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
                # Deterministic by construction: the file's size is a property
                # of the stored object, not of this moment — remember it.
                _neg_mark(chat, stem)
                _set_reason("deterministic")
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
                    fresh_leaf = _refresh_leaf(chat, stem, leaf,
                                               "stale manifest-index entry for")
                    if fresh_leaf:
                        leaf = fresh_leaf
                        r = rclone("copyto", f"{SRC}/{chat}/{leaf}", str(tmp_src))
                if r.returncode != 0:
                    # TRANSIENT (rclone/Drive transport) — never negative-cache.
                    print(f"[thumb] download original failed {chat}/{leaf}: "
                          f"rc={r.returncode} stderr={r.stderr[:300]!r}", flush=True)
                    _set_reason("transient")
                    return None
                make_thumb(tmp_src, local, is_video)
                # 3) persist to encrypted Drive cache (best effort, async-ish)
                rclone("copyto", str(local), f"{THUMBS}/{chat}/{stem}.jpg")
                if local.exists():
                    _neg_clear(chat, stem)  # generation succeeded; drop any old verdict
                    return local
                return None
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
                # Only a DECODE-level failure (bytes were fetched, then
                # rejected by Pillow/ffmpeg) is worth remembering. Transport /
                # permissions / space errors stay un-cached so the next
                # request retries normally.
                if _exc_is_deterministic(e):
                    _neg_mark(chat, stem)
                    _set_reason("deterministic")
                else:
                    _set_reason("transient")
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
        _gen_reason.value = None  # clear before ensure_thumb classifies the outcome
        thumb = ensure_thumb(chat, stem)
        if not thumb:
            # Report WHY generation failed so batch consumers (the backfill)
            # can tell a permanent decode verdict from a transient hiccup.
            # send_error() cannot carry custom headers, so build the 404 here.
            reason = getattr(_gen_reason, "value", None) or "unknown"
            body = json.dumps({"error": "thumb not available", "reason": reason}).encode()
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Thumb-Reason", reason)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
