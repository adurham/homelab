#!/usr/bin/env python3
"""
Tier-1 duplicate detector for the media gallery (perceptual hash).

Strategy: hash the THUMBNAILS (not originals) — they're small, resolution-
independent, and mostly already generated. We pull the whole encrypted thumb
tree down in ONE parallel rclone copy, compute a 64-bit dHash per image, then
group items whose hashes are within HAMMING_THRESHOLD of each other (0 = exact
visual match, higher = looser near-dupe). Result is written to
gcrypt:gallery/dedup.json for the SPA's "Find duplicates" view.

A second, semantic tier is intended to live in a separate analysis program and
is out of scope here.

dHash (no numpy/imagehash dep, pure Pillow):
  resize to 9x8 grayscale -> for each row compare adjacent pixels -> 64 bits.

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:),
     DEDUP_HAMMING (default 6), DEDUP_INCLUDE_VIDEO (default 0).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
GALLERY = REMOTE + "gallery"
THUMBS = REMOTE + "thumbs"
HAMMING = int(os.environ.get("DEDUP_HAMMING", "6"))
INCLUDE_VIDEO = os.environ.get("DEDUP_INCLUDE_VIDEO", "0") == "1"


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
    return bin(x).count("1")


def main():
    t0 = time.time()
    # load manifest to know which stems are current (and their chat/type)
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

    # pull the whole thumb tree locally in one parallel copy (fast vs N fetches)
    tdir = work / "thumbs"
    tdir.mkdir()
    log("downloading thumbnail tree…")
    r = rclone("copy", THUMBS, str(tdir),
               "--transfers", "32", "--checkers", "64",
               "--include", "*.jpg")
    if r.returncode != 0:
        log("thumb copy warning:", r.stderr[:200])

    # hash each item's thumbnail: thumbs/<chat>/<stem>.jpg
    hashes = {}  # stem -> int
    missing = 0
    for stem, it in items.items():
        tp = tdir / (it.get("chat") or "") / f"{stem}.jpg"
        if not tp.exists():
            missing += 1
            continue
        try:
            hashes[stem] = dhash(tp)
        except Exception as e:  # noqa: BLE001
            log(f"hash fail {stem}: {type(e).__name__}")
    log(f"hashed {len(hashes)} thumbnails ({missing} thumbs missing)")

    # group by Hamming distance (union-find). O(n^2) popcount on 64-bit ints is
    # fine for a few thousand items.
    stems = list(hashes.keys())
    parent = {s: s for s in stems}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    n = len(stems)
    for i in range(n):
        hi = hashes[stems[i]]
        for j in range(i + 1, n):
            if popcount(hi ^ hashes[stems[j]]) <= HAMMING:
                union(stems[i], stems[j])

    groups = {}
    for s in stems:
        groups.setdefault(find(s), []).append(s)

    # keep only real duplicate groups (2+ members); shape for the SPA
    dup_groups = []
    for members in groups.values():
        if len(members) < 2:
            continue
        # newest first within a group (manifest order ~ newest first)
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
    # biggest groups first
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

    # cleanup
    try:
        import shutil
        shutil.rmtree(work)
    except OSError:
        pass


if __name__ == "__main__":
    main()
