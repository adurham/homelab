#!/usr/bin/env python3
"""One-shot CLEANUP driver: remove legacy `.bin` ghost files from the store.

WHY THIS EXISTS (user request, 2026-10-01: "probably clean that up yeah"):

An older ingest path wrote uploaded media under ``<stem>.bin`` whenever the
source filename carried no extension that ``safe_ext()`` recognised. A
content-sniffing fix (``sniff_media_ext``, 2026-09-15) now recovers the real
type at ingest, so no NEW ``.bin`` should appear — but the pre-fix era left
thousands of them behind.

They are invisible dead weight, not gallery content:
  * ``build_manifest.py`` only recognises the image/video extension sets, so
    every ``.bin`` is silently skipped when the manifest is built — it never
    shows in the UI, is never de-duplicated, and is never tracked anywhere.
  * They are real bytes on the remote, so they are paid for on every sync.
  * The video thumbs/serving paths already have to PREFER a media sibling over
    the ``.bin`` for the same stem (see ``_prefer_media_leaf``), i.e. the app
    itself treats the ``.bin`` as the wrong copy when both exist.

Provenance of the two name shapes observed live:
  * ``<owner>_<postid>_source.bin`` / ``<owner>_<WxH>_<md5>_<a>_<b>.bin`` —
    same stem as a proper sibling, or sharing the sibling's post-id family.
  * ``<owner>_tempvid_<a>_<b>.bin`` / ``_tempaudio_...`` — a scraper naming
    quirk; the suffix was dropped at ingest, so the file has no extension.

CLASSIFICATION (dry-run reports the counts; only SAFE classes are deletable):

  REDUNDANT  — a sibling in the SAME folder exists whose name is the ``.bin``
               name minus ``.bin`` plus a known media extension, OR a sibling
               that carries the same embedded post-id token as the ``.bin``
               stem and a known media extension. The content is already stored
               properly, so the ``.bin`` is a ghost.

               NOTE ON SIZE: the ``.bin`` is typically SMALLER than its sibling
               (it is a truncated / partial download of the SAME object). It is
               therefore NOT byte-identical and a size guard would wrongly
               leave it in place. Do NOT require equal size here; the ghost is
               identified by the shared name/post-id, which is content
               provenance, not a coincidence. (Validated by direct byte reads:
               every sampled ``.bin`` was a byte-for-byte PREFIX of its
               sibling — same object, cut short.)

  AMBIGUOUS  — the ``.bin`` stem collides with a media sibling of the SAME
               stem key (name minus extension). ``/trashbatch`` resolves a
               stem by listing the folder and last-wins on
               ``os.path.splitext(leaf)[0]``; because ``.bin`` sorts before
               ``.mp4``, that map resolves the stem to the GOOD media file, so
               asking it to delete the stem would delete the wrong copy. These
               are reported for manual treatment and NEVER auto-deleted.

  ORPHAN     — no sibling found by either rule. NEVER deleted. Their bytes are
               sampled (magic-byte read) and collected into a report for human
               review, because they may be the ONLY stored copy of otherwise
               invisible content.

SAFETY RULES (read before changing anything here):
  1. Only the REDUNDANT class is ever deleted. ORPHAN and AMBIGUOUS are never
     touched by this tool.
  2. Deletion goes through the app's own /trashbatch endpoint — the single
     audited path — so every stem gets an exclusion-ledger entry and a
     removal-ledger record (reason=cleanup) automatically. NEVER delete via
     raw rclone here; that would bypass the audit trail. Note that the stem a
     ``.bin`` leaf contributes to /trashbatch is the name WITHOUT ``.bin``
     (os.path.splitext strips the LAST suffix only), which is what the service
     matches on.
  3. Batched + paced: N stems per call with a pause, so the remote API and the
     CT are never hammered. Transient connection-refused is retried with
     backoff.
  4. DRY RUN by default. Pass --apply to actually delete. Re-running is safe:
     already-deleted stems simply fail to resolve and are skipped.

Usage:
  # see what it WOULD delete (safe)
  python3 bin_ghost_cleanup.py
  # do it
  python3 bin_ghost_cleanup.py --apply
  # write the orphan report too
  python3 bin_ghost_cleanup.py --apply --orphan-report /tmp/orphans.json
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time

SRC = os.environ.get("BIN_CLEAN_SRC", "gcrypt:by-chat")
RCLONE_CONF = os.environ.get(
    "RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
TRASH_URL = os.environ.get("BIN_CLEAN_TRASH", "http://172.16.0.46:8091")
# Per-call batch size. /trashbatch builds one --include per leaf and runs a
# single rclone per folder, so keep each call bounded.
BATCH = 300
PAUSE = 1.5          # seconds between batches
RETRIES = 4

# Extension sets, kept in step with upload_service.py / build_manifest.py.
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
# Embedded post-id token shape (leading id inside the stem). Conservative:
# a run of >=10 lowercase alnum chars delimited by "_" boundaries.
POSTID_RE = re.compile(r"_([0-9a-z]{10,})")


def log(*a):
    print(*a, flush=True)


def rclone(*args):
    return subprocess.run(
        ["rclone", "--config", RCLONE_CONF, *args],
        capture_output=True, text=True)


def splitdir(path):
    return path.rsplit("/", 1) if "/" in path else ("", path)


def listing():
    """folder -> {leaf: size} for EVERY file under the remote, one walk.

    One recursive listing beats per-folder calls at this scale (thousands of
    files across hundreds of folders) and keeps the API load to a single pass.
    """
    r = rclone("lsf", f"{SRC}/", "--recursive", "--files-only", "--format", "sp")
    if r.returncode != 0:
        raise IOError(f"rclone lsf failed rc={r.returncode}: {r.stderr[:200]!r}")
    fol = collections.defaultdict(dict)
    for line in r.stdout.splitlines():
        if not line or ";" not in line:
            continue
        sz, path = line.split(";", 1)
        try:
            sz = int(sz)
        except ValueError:
            sz = -1
        d, leaf = splitdir(path)
        if leaf not in fol[d] or sz > fol[d][leaf]:
            fol[d][leaf] = sz
    return fol


def classify(fol):
    """Return (redundant, ambiguous, orphan) lists of (size, path, detail).

    redundant: (size, "folder/leaf", "folder/sibling")
    ambiguous: same-stem sibling exists -> unsafe for /trashbatch
    orphan:    nothing found
    """
    redundant, ambiguous, orphan = [], [], []
    for d, leaves in fol.items():
        for leaf, size in leaves.items():
            if not leaf.lower().endswith(".bin"):
                continue
            stem = os.path.splitext(leaf)[0]   # name minus the trailing .bin
            path = f"{d}/{leaf}"
            sibs = [(l2, sz2) for l2, sz2 in leaves.items() if l2 != leaf]
            # 1) exact same-stem media sibling -> AMBIGUOUS (stem collides;
            #    /trashbatch would resolve the stem to the media file).
            collide = [l2 for l2, _ in sibs
                       if os.path.splitext(l2)[0] == stem
                       and os.path.splitext(l2)[1].lower() in MEDIA_EXT]
            if collide:
                ambiguous.append((size, path, f"{d}/{collide[0]}"))
                continue
            # 2) post-id-family media sibling -> REDUNDANT.
            m = POSTID_RE.search(stem)
            hit = None
            if m:
                pid = m.group(1)
                for l2, _ in sibs:
                    if (os.path.splitext(l2)[1].lower() in MEDIA_EXT
                            and pid in l2):
                        hit = l2
                        break
            if hit:
                redundant.append((size, path, f"{d}/{hit}"))
            else:
                orphan.append((size, path, ""))
    return redundant, ambiguous, orphan


def sniff(remote_path):
    """First 16 bytes of a remote file, as hex (magic-byte identification).

    Uses `rclone cat --count 16` so ONLY 16 bytes are ever materialized —
    a plain `rclone cat` (or a `cat | head` shell pipe) would stream the whole
    file into memory, which is a real hazard when a report is asked for over a
    folder full of multi-GB items.
    """
    r = subprocess.run(
        ["rclone", "--config", RCLONE_CONF, "cat", remote_path, "--count", "16"],
        capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return ""
    return r.stdout[:16].hex()


def post_trashbatch(chat, stems):
    body = json.dumps({
        "chat": chat,
        "stems": stems,
        "reason": "cleanup",
        "detail": "legacy .bin ghost (misfiled pre-sniff-fix ingest; redundant "
                  "with a properly-named sibling)",
        "by": "bin_cleanup",
    }).encode()
    # curl (not urllib): urllib's timeout bounds each read, not the whole
    # transfer — a stalled peer has hung a sibling sweep on this box before.
    r = subprocess.run(
        ["curl", "-fsS", "--max-time", "280", "--retry", "2",
         "--retry-delay", "3", "-X", "POST",
         "-H", "Content-Type: application/json", "--data-binary", "@-",
         f"{TRASH_URL}/trashbatch"],
        input=body, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise IOError(f"trashbatch curl rc={r.returncode}: {r.stderr[:200]!r}")
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry run, report only)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--max-items", type=int, default=0,
                    help="cap total deletes this run (0 = no cap)")
    ap.add_argument("--orphan-report", default="",
                    help="write the orphan list (with sampled magic bytes) as JSON")
    ap.add_argument("--sniff-orphans", type=int, default=20,
                    help="how many orphan heads to sample for the report")
    args = ap.parse_args()

    t0 = time.time()
    log(f"listing {SRC}/ ...")
    fol = listing()
    total_files = sum(len(v) for v in fol.values())
    bins = sum(1 for v in fol.values() for l in v if l.lower().endswith(".bin"))
    log(f"listed {total_files} files across {len(fol)} folders; {bins} are .bin")

    redundant, ambiguous, orphan = classify(fol)
    red_bytes = sum(s for s, _, _ in redundant if s > 0)
    amb_bytes = sum(s for s, _, _ in ambiguous if s > 0)
    orp_bytes = sum(s for s, _, _ in orphan if s > 0)
    log("")
    log(f"  REDUNDANT (safe to delete)   : {len(redundant):6d}  "
        f"{red_bytes/1e9:8.3f} GB")
    log(f"  AMBIGUOUS (never auto-delete): {len(ambiguous):6d}  "
        f"{amb_bytes/1e9:8.3f} GB   (same-stem sibling; /trashbatch would "
        f"resolve to the media file)")
    log(f"  ORPHAN    (never delete)     : {len(orphan):6d}  "
        f"{orp_bytes/1e9:8.3f} GB")

    if args.orphan_report and orphan:
        sample = orphan[:args.sniff_orphans]
        log(f"\nsampling {len(sample)} orphan heads ...")
        rep = []
        for size, path, _ in orphan:
            rep.append({"path": path, "size": size})
        for i, (_sz, path, _sib) in enumerate(sample):
            rep[i]["head_hex"] = sniff(path)
        with open(args.orphan_report, "w") as f:
            json.dump({"count": len(orphan), "bytes": orp_bytes,
                       "items": rep}, f, indent=1)
        log(f"orphan report -> {args.orphan_report}")

    # group deletable stems by folder
    by_chat = collections.defaultdict(list)
    for _sz, path, _sib in redundant:
        d, leaf = splitdir(path)
        by_chat[d].append(os.path.splitext(leaf)[0])   # stem = name minus .bin
    total = sum(len(v) for v in by_chat.values())
    if args.max_items:
        left = args.max_items
        capped = {}
        for chat, stems in sorted(by_chat.items(), key=lambda kv: -len(kv[1])):
            if left <= 0:
                break
            take = stems[:left]
            capped[chat] = take
            left -= len(take)
        by_chat = capped
        total = sum(len(v) for v in by_chat.values())

    if not args.apply:
        log(f"\nDRY RUN — nothing deleted. Would delete {total} .bin ghosts "
            f"across {len(by_chat)} folders.")
        log("Top folders by count:")
        for chat, stems in sorted(by_chat.items(), key=lambda kv: -len(kv[1]))[:12]:
            log(f"   {len(stems):6d}  {chat}")
        log("\nRe-run with --apply to execute.")
        return 0

    done = failed = 0
    for ci, (chat, stems) in enumerate(
            sorted(by_chat.items(), key=lambda kv: -len(kv[1])), 1):
        for i in range(0, len(stems), args.batch):
            chunk = stems[i:i + args.batch]
            res = None
            last_err = None
            for attempt in range(RETRIES):
                try:
                    res = post_trashbatch(chat, chunk)
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    time.sleep(2 + 3 * attempt)
            if res is None:
                failed += len(chunk)
                log(f"  [{ci}/{len(by_chat)}] {chat}: BATCH FAILED after retries "
                    f"({type(last_err).__name__}: {last_err}) — resumable, "
                    f"already-deleted stems skip on the next run")
                continue
            d = int(res.get("deleted") or 0)
            done += d
            failed += max(0, len(chunk) - d)
            log(f"  [{ci}/{len(by_chat)}] {chat}: {d}/{len(chunk)} deleted "
                f"(running total {done}, {time.time()-t0:.0f}s)")
            time.sleep(args.pause)
    log(f"\nBIN CLEANUP DONE: {done} deleted, {failed} failed/skipped, "
        f"{time.time()-t0:.0f}s")
    log("Each deleted stem has a reason=cleanup record in the removal ledger "
        "and is in the exclusion ledger (handled by /trashbatch).")
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "60",
             f"{TRASH_URL}/deletions?reason=cleanup&limit=1"],
            capture_output=True, timeout=120)
        if r.returncode == 0:
            log(f"ledger summary now: {json.loads(r.stdout).get('summary') or {}}")
    except Exception as e:  # noqa: BLE001
        log(f"(ledger verify skipped: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
