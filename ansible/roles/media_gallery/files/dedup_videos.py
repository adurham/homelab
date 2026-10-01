#!/usr/bin/env python3
"""Video duplicate detection for the media gallery (2026-10-01).

WHY: dedup_scan.py only ever looked at IMAGES (dHash over thumbnails; videos
were explicitly excluded). Live measurement found 765 same-size video groups
holding ~1,408 extra copies = **~51 GB** of redundant storage, including
byte-identical pairs pushed from two different source accounts. Hiding images
without covering videos left the single biggest reclaim untouched.

APPROACH — two confidence tiers, because video is expensive to hash:

  TIER A ("upstream-id+size"): scraper stems embed the upstream post id
  (`<user>_<postid>[_source]`). Two items with the SAME post id and the SAME
  byte size are the same upstream object re-published to two accounts —
  mechanical evidence, matching the chat-id tier in the folder-identity
  hierarchy (see the media-gallery-app skill, pitfall 7). No bytes read.

  TIER B ("sha256-chunks"): same size, different ids. Verify by hashing three
  1 MiB chunks (head/mid/tail) through the LOCAL rclone HTTP serve, which
  supports range reads — a few MB per file instead of downloading the whole
  original (the same trick that made video posters viable). All three chunks
  matching on equal-sized files is overwhelming evidence of identity.

  Anything that can't be read is skipped, never guessed at.

Results are cached (stem -> chunk hash) so re-runs only verify NEW videos,
exactly like the image hash cache. The caller (dedup_scan.py) merges the
groups into dedup.json with kind="video" so the Duplicates review surfaces
them, and the hide path records them in the removal ledger.

Env: TG_RCLONE_REMOTE, RCLONE_CONFIG, DEDUP_VIDEO_* knobs.
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
SRC = REMOTE + "by-chat"
HTTP_BASE = os.environ.get("THUMB_VIDEO_HTTP_BASE", "http://172.16.0.46:8089")
CACHE_FILE = Path(os.environ.get("DEDUP_VIDEO_CACHE", "/var/lib/media-gallery/dedup_video_cache.json"))
CHUNK = int(os.environ.get("DEDUP_VIDEO_CHUNK", str(1 * 1024 * 1024)))
# Only bother verifying groups at or above this size (small videos are cheap
# anyway, and a 1MiB chunk read on a 2MB file is most of it).
MIN_VERIFY_BYTES = int(os.environ.get("DEDUP_VIDEO_MIN_BYTES", str(1 * 1024 * 1024)))
# Cap how many groups we verify per run so the hourly job stays bounded.
MAX_VERIFY_PER_RUN = int(os.environ.get("DEDUP_VIDEO_MAX_VERIFY", "400"))


def log(*a):
    print(*a, flush=True)


def _upstream_id(stem):
    """Extract the embedded upstream post id from a scraper stem, or None."""
    for tok in (stem or "").split("_"):
        if re.fullmatch(r"[0-9a-z]{19,24}", tok):
            return tok
    return None


def _load_cache():
    try:
        return json.loads(CACHE_FILE.read_text()) or {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(CACHE_FILE) + ".tmp"
        Path(tmp).write_text(json.dumps(cache, separators=(",", ":")))
        os.replace(tmp, CACHE_FILE)
    except OSError as e:
        log(f"[video-dedup] cache save failed: {e}")


def _chunk_hash(chat, leaf, offset, count):
    """sha256 of a byte range, via the local HTTP serve (range-capable).

    Uses curl rather than urllib for the fetch: urllib's socket timeout only
    bounds each individual read, so a peer that stalls mid-request can hang it
    indefinitely — observed live 2026-10-01: one range read froze a sweep for
    80+ minutes at zero IO and zero CPU. curl's --max-time is a HARD
    wall-clock cap on the whole transfer, so a stuck read always terminates
    (and then falls through to the rclone path).

    Falls back to `rclone cat --offset/--count` if the HTTP path fails, so a
    temporarily-down serve degrades to a slower-but-working verification."""
    import hashlib
    url = f"{HTTP_BASE}/by-chat/{chat}/{leaf}"
    h = hashlib.sha256()
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "90", "--retry", "1",
             "--retry-delay", "2",
             "-r", f"{offset}-{offset + count - 1}", url],
            capture_output=True, timeout=200)
        if r.returncode == 0 and r.stdout:
            h.update(r.stdout)
            return h.hexdigest()
        last = f"curl rc={r.returncode} stderr={r.stderr[:160]!r}"
    except Exception as e:  # noqa: BLE001 — fall through to the rclone path
        last = f"{type(e).__name__}: {e}"
    try:
        r = subprocess.run(
            ["rclone", "--config", RCLONE_CONF, "cat",
             "--offset", str(offset), "--count", str(count), f"{SRC}/{chat}/{leaf}"],
            capture_output=True, timeout=180)
        if r.returncode != 0 or not r.stdout:
            log(f"[video-dedup] chunk unreadable {chat}/{leaf}@{offset}: "
                f"http={last} rclone_rc={r.returncode}")
            return None
        h.update(r.stdout)
        return h.hexdigest()
    except Exception as e:  # noqa: BLE001
        log(f"[video-dedup] chunk unreadable {chat}/{leaf}@{offset}: "
            f"http={last} rclone={type(e).__name__}: {e}")
        return None


def _verify(chat, leaf, size, cache, stem):
    """Return a verification token for one file (cached). None = unreadable."""
    key = f"{stem}"
    hit = cache.get(key)
    if hit and hit.get("size") == size:
        return hit.get("sig")
    offsets = [0, max(0, size // 2), max(0, size - CHUNK)]
    sigs = []
    for off in offsets:
        sg = _chunk_hash(chat, leaf, off, min(CHUNK, max(1, size - off) or CHUNK))
        if sg is None:
            return None
        sigs.append(sg)
    sig = "|".join(sigs)
    cache[key] = {"size": size, "sig": sig, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return sig


def find_video_duplicates(items, max_verify=MAX_VERIFY_PER_RUN, progress=None):
    """items: manifest entries. Returns a list of groups, each a list of
    {stem, chat, thumb, file, date, size, kind, verified} (newest first).

    `max_verify` caps how many FILES Tier B will chunk-verify per run
    (0 = skip Tier B entirely, i.e. Tier A only — used for fast audits).

    2026-10-01 STABILITY FIX: this must NOT filter out already-hidden items.
    The hide ledger is rebuilt from these groups every run; excluding hidden
    members made a 2-member group disintegrate after its first hide, which
    UNHID the loser on the next hourly scan. Groups must be computed from the
    full membership set every time.
    """
    vids = [i for i in items if i.get("type") == "video"]
    by_size = defaultdict(list)
    for i in vids:
        sz = i.get("size") or 0
        if sz:
            by_size[sz].append(i)
    candidates = {sz: l for sz, l in by_size.items() if len(l) > 1}
    log(f"[video-dedup] {len(candidates)} same-size candidate groups "
        f"({sum(len(l) - 1 for l in candidates.values())} extra copies)")

    cache = _load_cache()
    groups = []
    verified_count = 0
    skipped = 0
    for sz, members in sorted(candidates.items(), reverse=True):
        # ---- TIER A: same upstream id (mechanical) ----
        by_id = defaultdict(list)
        for m in members:
            uid = _upstream_id(m.get("stem"))
            if uid:
                by_id[uid].append(m)
        id_groups = {u: l for u, l in by_id.items() if len(l) > 1}
        covered = set()
        for _uid, l in id_groups.items():
            covered.update(m["stem"] for m in l)
            groups.append(sorted(l, key=lambda m: m.get("date") or "", reverse=True))
            verified_count += len(l)
        rest = [m for m in members if m["stem"] not in covered]
        if len(rest) < 2:
            continue
        # ---- TIER B: same size, different ids -> chunk verification ----
        if sz < MIN_VERIFY_BYTES:
            # tiny videos: same size + same stem shape is weak; skip rather
            # than claim identity we didn't verify.
            skipped += len(rest) - 1
            continue
        if max_verify == 0 or (max_verify and verified_count >= max_verify):
            # 0 = audit mode (Tier A only); otherwise budget is exhausted.
            skipped += len(rest) - 1
            continue
        by_sig = defaultdict(list)
        unreadable = []
        for m in rest:
            leaf = os.path.basename(m.get("file") or "")
            if not leaf:
                unreadable.append(m)
                continue
            sig = _verify(m.get("chat") or "", leaf, sz, cache, m["stem"])
            verified_count += 1
            if sig is None:
                unreadable.append(m)
                continue
            by_sig[sig].append(m)
            if progress and verified_count % 20 == 0:
                progress(verified_count)
            if verified_count % 25 == 0:
                # Checkpoint: a kill or stall must not throw away the whole
                # run's verification work (the cache is ~70KB — saving is
                # cheap, and re-runs already skip everything cached).
                _save_cache(cache)
        for _sig, l in by_sig.items():
            if len(l) > 1:
                groups.append(sorted(l, key=lambda m: m.get("date") or "", reverse=True))
    _save_cache(cache)
    log(f"[video-dedup] verified {verified_count} files, "
        f"{len(groups)} duplicate groups, {skipped} deferred/unverifiable")
    return groups


def as_dedup_groups(groups):
    """Shape groups like dedup_scan's image groups (plus kind/verified)."""
    out = []
    for g in groups:
        out.append([{
            "stem": m.get("stem"),
            "chat": m.get("chat"),
            "thumb": m.get("thumb"),
            "file": m.get("file"),
            "date": m.get("date"),
            "size": m.get("size"),
            "kind": "video",
            "verified": "upstream-id+size" if all(
                _upstream_id(m.get("stem")) for m in g) and len({
                _upstream_id(m.get("stem")) for m in g}) == 1 else "sha256-chunks",
        } for m in g])
    return out


if __name__ == "__main__":
    # standalone: report only (never mutates anything)
    mpath = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/media-gallery/serve/gallery/manifest.json"
    items = json.loads(Path(mpath).read_text())
    gs = find_video_duplicates(items)
    total_extra = sum(len(g) - 1 for g in gs)
    total_bytes = sum(sum((m.get("size") or 0) for m in g[1:]) for g in gs)
    print(f"\n{len(gs)} groups, {total_extra} extra copies, "
          f"{total_bytes / 1e9:.1f} GB reclaimable")
    for g in gs[:10]:
        print(f"  {len(g)}x {(g[0].get('size') or 0)/1e6:.0f}MB: "
              f"{[ (m.get('chat'), m.get('stem')[:26]) for m in g[:3] ]}")
