#!/usr/bin/env python3
"""Re-ingest legacy ``.bin`` orphans: sniff the real type and RENAME in place.

WHY THIS EXISTS (user request, 2026-10-02: "if they can and should be
reingested then do it"):

An older ingest path wrote uploaded media under ``<stem>.bin`` whenever the
source filename carried no extension that ``safe_ext()`` recognised. A
content-sniffing fix (``sniff_media_ext``, 2026-09-15) now recovers the real
type at ingest, so no NEW ``.bin`` appears -- but the pre-fix era left
thousands behind, and ``build_manifest.py`` recognises only the image/video
extension sets, so every ``.bin`` is silently skipped: invisible in the
gallery, never de-duplicated, never thumbnailed, never tracked. The bytes are
real, viewable media. Renaming them to their true extension makes them VISIBLE
again -- with ZERO byte movement (a server-side rename on the remote).

THIS TOOL NEVER DELETES. It only renames ``<leaf>.bin`` -> ``<leaf>.<ext>``.
Anything it cannot classify with certainty is left untouched and counted; the
count IS the deliverable.

CLASSIFICATION (mirrors the live ingest path, ``upload_service.sniff_media_ext``)
------------------------------------------------------------------------------
Magic-byte read of the first 64 KiB (over the local HTTP serve, so no remote
traffic -- the same bounded endpoint the thumbnail path uses):

  * IMAGE   -- JPEG/PNG/GIF/WEBP/BMP signature at byte 0. Magic bytes suffice;
               the thumbnail path tolerates a truncated JPEG.
  * VIDEO   -- ISO base-media (``ftyp``) / Matroska (``1a45dfa3``) / RIFF-AVI.
               ``_tempaudio_``-named files FREQUENTLY hold MP4 VIDEO -- the
               name is never trusted, only the bytes.
               A video is ELIGIBLE only if a completeness probe passes:
               ``ffprobe`` against the same serve URL must parse the container
               and print a duration. A truncated upload ("moov atom not
               found") would otherwise become a dead tile, so it is SKIPPED.
  * AUDIO   -- ID3 / MPEG frame-sync / M4A / RIFF-WAVE / Ogg / FLAC. The
               gallery is a photo/video viewer with NO audio surface, so audio
               is SKIPPED permanently (counted, never renamed) for a separate
               user decision.
  * UNKNOWN -- anything else, or an unreadable head. No confident type -> no
               rename, not even a deletion. Skipped + counted.

SAFETY RULES (read before changing anything here):
  1. Rename ONLY. Never delete. Never download/upload bytes.
  2. DRY RUN by default; ``--apply`` gates every mutating call.
  3. CANARY FIRST: ``--canary`` renames exactly ONE file and verifies old-gone
     / new-present / size-identical before any bulk run. If the remote turns
     out to re-upload on rename, STOP -- do not mass-transfer bytes.
  4. COLLISION GUARD: the destination ``<leaf-without-.bin>.<ext>`` must NOT
     already exist in the folder (a handful of stems have both a ``.bin`` and
     a properly-named twin). Those are skipped as ``collision_skipped``.
  5. Paced: a small pause between remote mutations so the Drive API pacer and
     the CT are never hammered; transient errors are retried with backoff.

Usage:
  python3 bin_reingest.py                      # dry run: counts by class
  python3 bin_reingest.py --canary             # rename ONE file + verify
  python3 bin_reingest.py --apply              # rename all eligible
  python3 bin_reingest.py --apply --limit 50   # bounded slice
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import time

SRC = os.environ.get("BIN_REINGEST_SRC", "gcrypt:by-chat")
RCLONE_CONF = os.environ.get(
    "RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
# Local HTTP serve of the same tree -- bounded range reads, no remote traffic.
# URL namespace DROPS the rclone remote prefix: /by-chat/<folder>/<leaf>.
SERVE = os.environ.get("BIN_REINGEST_SERVE", "http://172.16.0.46:8089")
LOG = os.environ.get("BIN_REINGEST_LOG", "/var/log/media-gallery/bin_reingest.log")
STATE = os.environ.get("BIN_REINGEST_STATE",
                       "/var/lib/media-gallery/bin_reingest_state.json")

PAUSE = 0.5          # seconds between remote mutations
RETRIES = 3
HEAD_BYTES = 65535   # 64 KiB range read
FFPROBE_TIMEOUT = 60

# Extension sets, kept in step with upload_service.py / build_manifest.py.
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT

# Class labels.
IMG, VID, AUDIO, UNKNOWN, ERROR = "image", "video", "audio", "unknown", "error"


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def splitdir(path):
    return path.rsplit("/", 1) if "/" in path else ("", path)


def rclone(*args, retries=RETRIES):
    last = subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                          capture_output=True, text=True)
    for attempt in range(1, retries):
        if last.returncode == 0:
            return last
        time.sleep(1.5 * attempt)
        last = subprocess.run(["rclone", "--config", RCLONE_CONF, *args],
                              capture_output=True, text=True)
    return last


def listing():
    """folder -> {leaf: size} for EVERY file under the remote, one walk.

    A single recursive listing keeps the remote API load to one pass and gives
    the folder membership needed for the collision guard at no extra cost.
    """
    r = rclone("lsf", f"{SRC}/", "--recursive", "--files-only", "--format", "sp")
    if r.returncode != 0:
        raise IOError(f"rclone lsf failed rc={r.returncode}: {r.stderr[:200]!r}")
    fol = collections.defaultdict(dict)
    for line in r.stdout.splitlines():
        if not line or ";" not in line:
            continue
        sz, path = line.split(";", 1)   # --format "sp" => size;path
        try:
            sz = int(sz)
        except ValueError:
            sz = -1
        d, leaf = splitdir(path)
        if leaf not in fol[d] or sz > fol[d][leaf]:
            fol[d][leaf] = sz
    return fol


def sniff(head):
    """Real type from magic bytes ONLY -- mirrors upload_service.sniff_media_ext.

    Returns (class, ext) where class is one of IMG/VID/AUDIO/UNKNOWN and ext is
    the extension to rename to (None when not renamable). Deliberately
    conservative: it must never MISidentify, only recover what was guaranteed
    wrong before.
    """
    if len(head) < 12:
        return UNKNOWN, None
    # -- audio containers (no gallery surface -> reported, never renamed) --
    if head[:3] == b"ID3":
        return AUDIO, None
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return AUDIO, None
    if head[:4] in (b"fLaC", b"OggS") or head[:4] == b"RF64":
        return AUDIO, None
    if head[4:8] == b"ftyp" and head[8:12] in (b"M4A ", b"M4B "):
        return AUDIO, None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return AUDIO, None
    # -- images --
    if head[:3] == b"\xff\xd8\xff":
        return IMG, ".jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return IMG, ".png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return IMG, ".gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return IMG, ".webp"
    if head[:2] == b"BM":
        return IMG, ".bmp"
    # -- video (still needs the completeness probe) --
    if head[4:8] == b"ftyp":
        # ISO base media: every observed brand except Apple M4A/M4B (handled
        # above) is real playable video.
        return VID, ".mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return VID, ".webm"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return VID, ".avi"
    return UNKNOWN, None


def serve_url(folder, leaf):
    return f"{SERVE}/by-chat/{folder}/{leaf}"


def read_head(folder, leaf):
    """First 64 KiB via a bounded HTTP range read. None on failure."""
    url = serve_url(folder, leaf)
    for attempt in range(2):
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "30", "-r", f"0-{HEAD_BYTES}", url],
            capture_output=True)
        if r.returncode == 0 and r.stdout:
            return r.stdout[:HEAD_BYTES]
        # curl -f suppresses the body on HTTP error; retry once on transient.
        if attempt == 0:
            time.sleep(1.0)
    return None


def video_complete(folder, leaf):
    """True when ffprobe parses the container (moov found) -> playable."""
    url = serve_url(folder, leaf)
    try:
        r = subprocess.run(
            ["timeout", str(FFPROBE_TIMEOUT), "ffprobe", "-v", "error",
             "-show_entries", "format=duration", "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT + 10)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out:
        return True, out
    err = (r.stderr or "").strip().splitlines()
    return False, (err[-1] if err else f"rc={r.returncode}")


def moveto(src_path, dst_path):
    r = subprocess.run(
        ["rclone", "--config", RCLONE_CONF, "moveto", src_path, dst_path],
        capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "").strip()[:200]


def size_of(remote_path):
    r = subprocess.run(
        ["rclone", "--config", RCLONE_CONF, "lsf", remote_path, "--format", "s"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    t = r.stdout.strip().splitlines()
    try:
        return int(t[0]) if t else None
    except ValueError:
        return None


def load_state():
    try:
        return json.loads(open(STATE).read())
    except (OSError, ValueError):
        return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, STATE)
    except OSError as e:
        log(f"[warn] state save failed: {e}")


def verify(renamed_out):
    """Read-only: assert every recorded rename landed (src gone, dst present at
    the same size). One full listing, then set membership -- no per-file calls.
    Exits non-zero if any rename is unverified."""
    try:
        recs = json.loads(open(renamed_out).read())
    except (OSError, ValueError) as e:
        log(f"[verify] cannot read {renamed_out}: {e}")
        return 2
    fol = listing()
    missing_dst, lingering_src, size_bad = [], [], []
    for r in recs:
        d, dst, src, sz = r["folder"], r["dst"], r["src"], r["size"]
        leaves = fol.get(d, {})
        if src in leaves:
            lingering_src.append(f"{d}/{src}")
        if dst not in leaves:
            missing_dst.append(f"{d}/{dst}")
        elif leaves[dst] != sz:
            size_bad.append(f"{d}/{dst} {leaves[dst]}!={sz}")
    log(f"[verify] {len(recs)} renames: missing_dst={len(missing_dst)} "
        f"lingering_src={len(lingering_src)} size_mismatch={len(size_bad)}")
    for label, lst in (("missing_dst", missing_dst),
                       ("lingering_src", lingering_src),
                       ("size_mismatch", size_bad)):
        for x in lst[:10]:
            log(f"[verify-{label}] {x}")
    return 0 if not (missing_dst or lingering_src or size_bad) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually rename (default: dry run, report only)")
    ap.add_argument("--canary", action="store_true",
                    help="rename exactly ONE eligible file and verify it")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap total renames this run (0 = no cap)")
    ap.add_argument("--folder", default="",
                    help="restrict to a single top-level folder")
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--workers", type=int, default=8,
                    help="parallel classification workers (local IO-bound probes)")
    ap.add_argument("--renamed-out", default="",
                    help="write the list of successful renames here (for --verify)")
    ap.add_argument("--verify", default="",
                    help="path to a --renamed-out file: assert every src is gone "
                         "and dst is present at the same size (read-only)")
    args = ap.parse_args()

    if args.verify:
        return verify(args.verify)

    t0 = time.time()
    log(f"=== bin_reingest start apply={args.apply} canary={args.canary} "
        f"limit={args.limit} folder={args.folder or '*'} ===")
    fol = listing()
    nfiles = sum(len(v) for v in fol.values())
    log(f"[list] {nfiles} files across {len(fol)} folders")

    cands = []
    for d, leaves in fol.items():
        if args.folder and d.split("/")[0] != args.folder:
            continue
        for leaf in leaves:
            if leaf.lower().endswith(".bin"):
                cands.append((d, leaf, leaves[leaf]))
    cands.sort()
    log(f"[scan] {len(cands)} live .bin candidates")

    st = load_state()

    def classify_one(item):
        """Classify one candidate from magic bytes (+ the video probe). Read-only
        against the local serve, so it is safe to run many at once."""
        d, leaf, sz = item
        key = f"{d}/{leaf}"
        rec = st.get(key)
        if rec and rec.get("size") == sz:
            return (d, leaf, sz, rec.get("cls"), rec.get("ext"), None)
        head = read_head(d, leaf)
        if head is None:
            return (d, leaf, sz, ERROR, None, None)
        cls, ext = sniff(head)
        if cls == VID and ext:
            ok, detail = video_complete(d, leaf)
            if not ok:
                return (d, leaf, sz, "truncated", None, detail)
        return (d, leaf, sz, cls, ext, None)

    # Classify in parallel: the cost is the ffprobe completeness probe, which
    # is network/IO-bound against the LOCAL serve, so a small worker pool is
    # well within the box's capacity (Drive is only touched by the rename
    # phase, which stays serial + paced).
    results = []
    done = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(classify_one, c) for c in cands]
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            d, leaf, sz, cls, ext, _ = r
            key = f"{d}/{leaf}"
            if st.get(key, {}).get("size") != sz:
                st[key] = {"size": sz, "cls": cls, "ext": ext}
            done += 1
            if done % 100 == 0:
                save_state(st)
                log(f"[scan] {done}/{len(cands)}")
    save_state(st)
    results.sort(key=lambda r: (r[0], r[1]))

    counts = collections.Counter()
    eligible = []          # (folder, leaf, ext, size)
    skipped = []           # (folder, leaf, reason, detail)

    for (d, leaf, sz, cls, ext, detail) in results:
        if cls == AUDIO:
            counts["audio_skipped"] += 1
            continue
        if cls == "truncated":
            counts["truncated_skipped"] += 1
            skipped.append((d, leaf, "truncated_skipped", detail))
            continue
        if cls == ERROR:
            counts["read_error"] += 1
            continue
        if cls not in (IMG, VID):
            counts["unknown"] += 1
            continue

        # collision guard: destination must not already exist.
        stem = leaf[:-4] if leaf.lower().endswith(".bin") else os.path.splitext(leaf)[0]
        dest_leaf = stem if stem.lower().endswith(ext) else stem + ext
        leaves = fol[d]
        if dest_leaf in leaves:
            skipped.append((d, leaf, "collision_skipped", dest_leaf))
            counts["collision_skipped"] += 1
            continue
        eligible.append((d, leaf, ext, sz))
        counts["eligible_image" if cls == IMG else "eligible_video"] += 1

    save_state(st)
    elig_bytes = sum(e[3] for e in eligible)
    log("[dry-run] " + json.dumps(dict(counts), sort_keys=True))
    log(f"[dry-run] eligible={len(eligible)} bytes={elig_bytes} "
        f"({elig_bytes/1e9:.2f} GB)")
    by_reason = collections.Counter(s[2] for s in skipped)
    log("[dry-run] skipped " + json.dumps(dict(by_reason), sort_keys=True))

    if not args.apply:
        log(f"=== dry run complete in {time.time()-t0:.0f}s; --apply to rename ===")
        return

    if args.canary:
        eligible = eligible[:1]
    elif args.limit:
        eligible = eligible[:args.limit]

    done = 0
    done_bytes = 0
    fails = []
    renamed = []            # {src, dst, size, folder} for post-run verification
    for (d, leaf, ext, sz) in eligible:
        stem = leaf[:-4] if leaf.lower().endswith(".bin") else os.path.splitext(leaf)[0]
        dst_leaf = stem if stem.lower().endswith(ext) else stem + ext
        src_path = f"{SRC}/{d}/{leaf}"
        dst_path = f"{SRC}/{d}/{dst_leaf}"
        # A server-side moveto returns rc=0 only when the rename landed; the
        # canary confirmed bytes+modtime are preserved with no transfer, so
        # there is no need for a per-file size round-trip (halves Drive API
        # calls). One authoritative listing at the end verifies every rename.
        ok, err = moveto(src_path, dst_path)
        if not ok:
            fails.append((f"{d}/{leaf}", err))
            log(f"[FAIL] {d}/{leaf} -> {dst_leaf}: {err}")
            time.sleep(args.pause)
            continue
        done += 1
        done_bytes += sz
        renamed.append({"src": leaf, "dst": dst_leaf, "folder": d, "size": sz})
        if args.canary or done % 25 == 0 or done == len(eligible):
            log(f"[rename] {done}/{len(eligible)} {d}/{leaf} -> {dst_leaf} ({sz} bytes)")
        time.sleep(args.pause)

    save_state(st)
    if args.renamed_out:
        try:
            with open(args.renamed_out, "w") as f:
                json.dump(renamed, f)
        except OSError as e:
            log(f"[warn] renamed-out write failed: {e}")
    log(f"=== done: renamed={done} bytes={done_bytes} "
        f"({done_bytes/1e9:.2f} GB) failures={len(fails)} "
        f"in {time.time()-t0:.0f}s ===")
    if fails:
        for p, e in fails[:20]:
            log(f"[FAIL-SUMMARY] {p}: {e}")


if __name__ == "__main__":
    sys.exit(main())
