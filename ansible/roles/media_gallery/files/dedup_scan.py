#!/usr/bin/env python3
"""
Tier-1 duplicate detector for the media gallery (perceptual hash).

v2 (2026-09-12) — INCREMENTAL + LSH-BANDED, safe to run on every hourly
refresh instead of only on-demand via a manual "Scan now" click.

Why this rewrite: the v1 scanner (a) re-hashed every thumbnail from scratch
every run, and (b) compared every pair of hashes (O(n^2)). At ~130k items
that's ~8.4 BILLION popcount comparisons — ~90 minutes in practice on this
box. That made the report only ever get regenerated when someone remembered
to click "Scan now" and wait — in reality it sat stale for 3+ months, during
which real user deletes and new content silently diverged from the report
(deleted items kept showing as duplicates forever; new duplicates were never
detected at all). Two changes fix both the correctness AND cost problem:

1. INCREMENTAL HASHING: a persistent stem -> hash cache on disk
   (HASH_CACHE_FILE). Only thumbnails for stems not already in the cache get
   downloaded + hashed. A thumbnail's content never changes once generated
   (it's keyed by stem, produced once by thumb_service.py), so a hash is
   valid forever once computed — no re-hash, no re-download, ever, for a
   stem already seen. Stems no longer in the manifest (deleted) are pruned
   from the cache each run so it can't grow without bound.

2. LSH BANDING instead of brute-force O(n^2): split each 64-bit dHash into
   8 non-overlapping 8-bit bands. Two hashes matching EXACTLY in any one
   band are a "candidate pair" — only candidate pairs get the real (precise)
   Hamming-distance check. This is lossless at HAMMING<=6: by pigeonhole,
   distributing at most 6 differing bits across 8 bands means at least
   8-6=2 bands must be error-free, so every true match is guaranteed to
   share at least one exact band and always gets found. (This stops being
   an exact guarantee only if HAMMING is ever raised above 7 — see the
   assertion below.) Turns ~130k^2/2 comparisons into candidate-bucket-sized
   chunks — buckets average n/256 items each, so cost is roughly
   n^2/256 per band * 8 bands ~= n^2/32, a >30x cut, and unlike the flat
   O(n^2), it scales with actual visual clustering, not just item count.

Combined, a full COLD run (empty cache) mostly reads thumbnails straight off
the local prewarm cache (see THUMB_LOCAL_CACHE below) that prewarm_thumbs.sh
already maintains and refresh_gallery.sh runs immediately before this
script — so even a cold hash pass over ~165k items costs local disk I/O +
CPU, not a fresh multi-GB download from Drive. Every run AFTER that only
hashes genuinely new items (seconds), making the whole thing cheap enough to
chain onto the existing hourly refresh_gallery.sh instead of needing a human
to remember to click a button.

Result is written to gcrypt:gallery/dedup.json for the SPA's "Find
duplicates" view (which additionally live-filters against the current
manifest client-side — see gallery_index.html renderDuplicates — so even a
report that's an hour old can never show an already-deleted item as if it
still existed).

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:),
     DEDUP_HAMMING (default 6, MUST be <=7 for the banding guarantee below),
     DEDUP_INCLUDE_VIDEO (default 0), DEDUP_HASH_CACHE (path).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import fcntl
from pathlib import Path

from PIL import Image

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
GALLERY = REMOTE + "gallery"
THUMBS = REMOTE + "thumbs"
HAMMING = int(os.environ.get("DEDUP_HAMMING", "6"))
INCLUDE_VIDEO = os.environ.get("DEDUP_INCLUDE_VIDEO", "0") == "1"
HASH_CACHE_FILE = Path(os.environ.get(
    "DEDUP_HASH_CACHE", "/var/lib/media-gallery/dedup_hash_cache.json"))
LOCK_FILE = Path(os.environ.get(
    "DEDUP_LOCK_FILE", "/var/lock/media-gallery-dedup-scan.lock"))
# The SAME persistent local thumbnail mirror prewarm_thumbs.sh maintains
# (refresh_gallery.sh runs prewarm right before this script). Reading from
# here first means dedup_scan.py rides on work the refresh cycle has
# already done, instead of re-downloading from Drive into a throwaway temp
# dir every run. This was the actual fix for the cold-run slowness found
# live 2026-09-12: bulk-copying into a FRESH empty tmpdir every time re-pulls
# the whole ~2.4GB tree from scratch regardless of what's already local,
# while this cache is already ~98%+ populated in steady state (per
# prewarm_thumbs.sh's own comments) and gets refreshed just seconds before
# this script runs in the same refresh_gallery.sh invocation.
THUMB_LOCAL_CACHE = Path(os.environ.get(
    "THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
NUM_BANDS = 8
BAND_BITS = 8  # 8 bands * 8 bits = 64 bits, exactly covers the dHash

# The banding scheme below only GUARANTEES catching every pair within
# HAMMING bits if HAMMING < NUM_BANDS (pigeonhole: HAMMING errors spread
# across NUM_BANDS bands leaves at least NUM_BANDS-HAMMING error-free
# bands). Fail loudly rather than silently miss real duplicates if someone
# bumps DEDUP_HAMMING past what banding can still guarantee.
assert HAMMING < NUM_BANDS, (
    f"DEDUP_HAMMING={HAMMING} must be < {NUM_BANDS} for banded candidate "
    f"generation to be lossless; raise NUM_BANDS/lower BAND_BITS first")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def dhash(path, size=8):
    """64-bit difference hash as a Python int."""
    with Image.open(path) as im:
        im = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(im.getdata())
    w = size + 1
    bits = 0
    for row in range(size):
        base = row * w
        for col in range(size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def popcount(x):
    # int.bit_count() is a native C-level popcount (Python 3.10+, confirmed
    # available: this box runs 3.10.12) — meaningfully faster than the old
    # bin(x).count("1") string round-trip once run millions of times.
    return x.bit_count()


def load_hash_cache() -> dict:
    """stem -> hash (as a hex string, JSON-safe). Missing/corrupt -> empty."""
    try:
        with open(HASH_CACHE_FILE) as f:
            raw = json.load(f)
        return {k: int(v, 16) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_hash_cache(cache: dict):
    HASH_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(HASH_CACHE_FILE) + ".tmp"
    raw = {k: format(v, "x") for k, v in cache.items()}
    Path(tmp).write_text(json.dumps(raw, separators=(",", ":")))
    os.replace(tmp, HASH_CACHE_FILE)


def band_values(h: int):
    """Split a 64-bit hash into NUM_BANDS band values (0..255 each)."""
    mask = (1 << BAND_BITS) - 1
    return tuple((h >> (b * BAND_BITS)) & mask for b in range(NUM_BANDS))


def candidate_pairs(hashes: dict):
    """LSH banding: yield each unique (stem_a, stem_b) pair that shares at
    least one exact band value. Guaranteed superset of every true pair
    within HAMMING distance (see module docstring/assert above)."""
    stems = list(hashes.keys())
    bands = {s: band_values(hashes[s]) for s in stems}
    seen_pairs = set()
    for band_idx in range(NUM_BANDS):
        buckets = {}
        for s in stems:
            buckets.setdefault(bands[s][band_idx], []).append(s)
        for members in buckets.values():
            if len(members) < 2:
                continue
            n = len(members)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = members[i], members[j]
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    yield pair


def main():
    # Guard against overlapping runs (the shell wrapper refresh_gallery.sh
    # already flocks the whole refresh sequence, but this script can also be
    # invoked standalone -- e.g. for manual testing, as happened live
    # 2026-09-12 when a foreground test run collided with the hourly timer
    # and both processes raced on HASH_CACHE_FILE / dedup.json). Fail fast
    # (non-blocking) rather than queue: a skipped run just means the next
    # scheduled one picks up the same incremental work shortly after.
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another dedup_scan.py run is already in progress — skipping")
        sys.exit(0)

    t0 = time.time()
    work = Path(tempfile.mkdtemp(prefix="dedup_"))
    mp = work / "manifest.json"
    r = rclone("copyto", f"{GALLERY}/manifest.json", str(mp))
    if r.returncode != 0:
        log("cannot fetch manifest:", r.stderr[:200])
        sys.exit(1)
    manifest = json.loads(mp.read_text())
    items = {it["stem"]: it for it in manifest
             if INCLUDE_VIDEO or it.get("type") != "video"}
    log(f"manifest items to hash: {len(items)} (videos {'in' if INCLUDE_VIDEO else 'ex'}cluded)")

    # ---- incremental: only hash stems we haven't seen before ----
    hashes = load_hash_cache()
    before_cache = len(hashes)
    # prune dead stems (deleted since last run) so the cache can't grow
    # without bound and never re-surfaces a ghost via a stale cache hit
    dead = set(hashes) - set(items)
    for s in dead:
        del hashes[s]
    new_stems = [s for s in items if s not in hashes]
    log(f"hash cache: {before_cache} cached, {len(dead)} pruned (deleted), "
        f"{len(new_stems)} new to hash")

    if new_stems:
        log(f"resolving {len(new_stems)} new thumbnail(s)…")
        # STEP 1: check the already-populated local prewarm cache first (see
        # THUMB_LOCAL_CACHE comment above) — this is normally almost every
        # item, since prewarm_thumbs.sh runs immediately before this script
        # in refresh_gallery.sh and that cache is already ~98%+ complete in
        # steady state. Zero network cost for anything found here.
        still_missing = []
        found_local = 0
        for s in new_stems:
            chat = items[s].get("chat") or ""
            lp = THUMB_LOCAL_CACHE / chat / f"{s}.jpg"
            if lp.exists():
                try:
                    hashes[s] = dhash(lp)
                    found_local += 1
                except Exception as e:  # noqa: BLE001
                    log(f"hash fail (local) {s}: {type(e).__name__}")
                    still_missing.append(s)
            else:
                still_missing.append(s)
        log(f"found {found_local} in the local prewarm cache, "
            f"{len(still_missing)} need fetching from Drive")

        # STEP 2: anything not already local (a handful in steady state; a
        # real gap on a cold run — see below) — fetch in ONE rclone
        # invocation using --files-from (an exact-path list, NOT --include
        # patterns). Confirmed via reference-model consult 2026-09-12 after
        # the chunked --include approach proved far slower than expected
        # even for "only" tens of thousands of files: --include chat/stem.jpg
        # is UNANCHORED (no leading /), so rclone can't derive a directory
        # prune from it and instead walks the ENTIRE remote tree on every
        # single chunked invocation, evaluating every chunk's ~500 include
        # regexes (plus the implicit trailing exclude-all) against every one
        # of the ~130k listed entries — no amount of chunking fixes an
        # O(tree_size) per-invocation cost paid 100+ times. --files-from
        # makes rclone build a set of exact parent directories to list
        # instead, giving ONE proper prune + ONE pass regardless of how many
        # files are requested.
        #
        # Writes go straight into THUMB_LOCAL_CACHE (the real persistent
        # cache), not a disposable temp dir — a file fetched here becomes
        # part of the same cache prewarm_thumbs.sh maintains, so the next
        # run (this script's or prewarm's) never re-fetches it. This was the
        # other real fix: the old code fetched into a fresh tempdir every
        # run, so a partial/interrupted run's downloads were thrown away
        # instead of banked.
        #
        # A stem can be "still_missing" locally for two different reasons:
        # (a) genuinely not yet on the remote at all (thumb_service.py
        #     generates thumbnails lazily/on first view — a rarely-viewed
        #     item may just never have had one made), or
        # (b) present remotely but prewarm hasn't synced it down yet.
        # We can't tell which without asking the remote, so: try the fetch;
        # whatever's STILL missing after it stays out of the hash cache and
        # will be retried on the NEXT run too — acceptable because the fetch
        # itself is now one fast --files-from invocation (not the old
        # per-invocation-overhead chunked --include loop), so retrying a
        # genuinely-absent item every hour is cheap. If this ever needs to
        # stop retrying permanently-thumbnail-less items, add a real TTL/
        # negative-cache file — not attempted here to keep this change
        # focused on the actual perf bug found live.
        if still_missing:
            files_list = work / "files_from.txt"
            with open(files_list, "w") as f:
                for s in still_missing:
                    chat = items[s].get("chat") or ""
                    f.write(f"{chat}/{s}.jpg\n")
            THUMB_LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
            r = rclone("copy", THUMBS, str(THUMB_LOCAL_CACHE),
                       "--files-from", str(files_list),
                       "--transfers", "32", "--checkers", "32")
            if r.returncode != 0:
                log("files-from thumb copy warning:", r.stderr[:300])

            missing = 0
            for stem in still_missing:
                it = items[stem]
                tp = THUMB_LOCAL_CACHE / (it.get("chat") or "") / f"{stem}.jpg"
                if not tp.exists():
                    missing += 1
                    continue
                try:
                    hashes[stem] = dhash(tp)
                except Exception as e:  # noqa: BLE001
                    log(f"hash fail (fetched) {stem}: {type(e).__name__}")
            log(f"fetched+hashed {len(still_missing) - missing} from Drive "
                f"({missing} genuinely absent from the remote right now — "
                f"thumb_service.py likely hasn't generated them yet)")

    else:
        log("no new items to hash — cache fully up to date")

    save_hash_cache(hashes)

    # ---- LSH-banded candidate generation, then precise Hamming check ----
    log(f"banding {len(hashes)} hashes into candidate pairs…")
    parent = {s: s for s in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    n_candidates = 0
    n_confirmed = 0
    for a, b in candidate_pairs(hashes):
        n_candidates += 1
        if popcount(hashes[a] ^ hashes[b]) <= HAMMING:
            n_confirmed += 1
            union(a, b)
    log(f"candidate pairs: {n_candidates:,}, confirmed duplicates: {n_confirmed:,}")

    groups = {}
    for s in hashes:
        groups.setdefault(find(s), []).append(s)

    dup_groups = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members_sorted = sorted(
            members, key=lambda s: items[s].get("date") or "", reverse=True)
        dup_groups.append([{
            "stem": s,
            "chat": items[s].get("chat"),
            "thumb": items[s].get("thumb"),
            "file": items[s].get("file"),
            "date": items[s].get("date"),
            "size": items[s].get("size"),
        } for s in members_sorted])
    dup_groups.sort(key=len, reverse=True)

    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hamming": HAMMING,
        "scanned": len(hashes),
        "groups": dup_groups,
        "dup_items": sum(len(g) for g in dup_groups),
        "dup_groups": len(dup_groups),
    }
    op = work / "dedup.json"
    op.write_text(json.dumps(out, separators=(",", ":")))
    r = rclone("copyto", str(op), f"{GALLERY}/dedup.json")
    if r.returncode != 0:
        log("upload dedup.json failed:", r.stderr[:200])
        sys.exit(1)
    log(f"dedup.json: {len(dup_groups)} groups, {out['dup_items']} items, "
        f"{time.time() - t0:.1f}s — DONE")

    try:
        import shutil
        shutil.rmtree(work)
    except OSError:
        pass


if __name__ == "__main__":
    main()
