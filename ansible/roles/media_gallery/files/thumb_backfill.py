#!/usr/bin/env python3
"""
One-time (or run-as-needed), THROTTLED backfill: generate thumbnails for
manifest items that have never been viewed in the gallery UI, and so have
never had a thumbnail created at all.

PERFORMANCE FIX (2026-09-15): originally this hit thumb_service.py's live
HTTP endpoint per item (see the module's own prior docs, and the Usage
section below for the still-supported --http-fallback flag). Measured live:
that was taking ~26s/item against large backlogged folders, not the ~2.5s
this tool's docs assumed -- root cause is thumb_service.py's find_original()
doing a FULL `rclone lsf` of the entire chat folder to locate the original's
exact filename by prefix-matching the stem (correct for its real job: a live
page-view request that only has {chat, stem}, not the full leaf filename).
For a 7249-item folder that single listing call took 23s, confirmed via a
direct timing test, and it's paid on EVERY item, not once per folder.

This script doesn't have that excuse: it already downloaded the full
manifest, which carries each item's leaf filename directly, so it can call
thumb_service.make_thumb() locally and skip find_original() (and the whole
HTTP round-trip) entirely for images -- the manifest already told us
exactly which file to open. This does NOT touch thumb_service.py's live
serving path or its request-time correctness/space-reservation logic in any
way; it only changes how THIS offline batch tool resolves originals. (The
live per-view stall itself is a separate, real finding worth its own fix in
thumb_service.py -- flagged, not fixed here, since it wasn't in scope for
"run the backfill.")

Video posters (--include-video, opt-in and not the default) still go
through the HTTP path unchanged -- thumb_service.py's video-poster
generation has real space-reservation and prefix-streaming logic for
multi-GB files that isn't worth re-implementing here for a rarely-used
flag; the fast local path below only covers images.

WHY THIS EXISTS (2026-09-12): dedup_scan.py's duplicate detector can only
hash items that already have a thumbnail in gcrypt:thumbs/ (thumbnails are
normally generated lazily, on first view, by thumb_service.py). Found live:
~60,711 of ~165,000 gallery items (37%) have NEVER been viewed and so have
no thumbnail at all — meaning the dedup report is blind to any duplicate
pair where at least one side is in that unviewed set. Per a reference-model
consult: this is worse than the raw 37% suggests at the PAIR level (if
viewedness is roughly independent of duplicate-ness, pair-level detection
coverage is closer to 0.63^2 ~= 40%, worse for larger groups) — so this is
a real, material gap in "does the dedupe scanner actually work," not a
cosmetic one.

WHY THIS IS A SEPARATE SCRIPT, NOT PART OF dedup_scan.py or its hourly
timer: generating a thumbnail from scratch costs a real download-original +
resize + re-upload-to-Drive round trip (thumb_service.py's own comments
put this at ~2.5s cold, historically). 60,711 of those synchronously inside
an hourly job would blow through the hour, overlap runs, and compete with
thumb_service.py for the same Drive API quota that REAL user page-views
need right now. This script is meant to be run BY THE USER, by hand, when
they want to pay that one-time cost — not something dedup_scan.py or any
timer invokes automatically.

DESIGN:
- Resumable: the missing-list is recomputed fresh each run (manifest minus
  what's already in gcrypt:thumbs/), so killing this at any point and
  re-running just picks up wherever it left off. No separate progress file
  to get out of sync.
- Throttled: hits thumb_service.py's own HTTP endpoint (the same code path
  a real page-view takes — reuses all its existing locking/space-reservation
  logic rather than duplicating it), one item at a time, with a configurable
  delay between requests. Defaults are deliberately conservative (see
  BACKFILL_DELAY_SEC) to avoid hammering the same Drive API quota
  thumb_service.py needs for real live traffic.
- Budgeted: --budget N processes at most N items this run and exits cleanly,
  so this can be left running in a screen/tmux session, or invoked
  repeatedly via cron with a small budget, without needing to babysit a
  multi-day process.
- Bandwidth-aware: prints a running estimate of data pulled (original file
  sizes), since backfilling 60k originals is a real bandwidth cost on a
  home connection, not just an API-quota cost — the user should be able to
  see that cost accumulate and stop early if needed.

Usage:
  ./venv/bin/python thumb_backfill.py --budget 500         # do 500, then exit
  ./venv/bin/python thumb_backfill.py --budget 500 --delay 3.0
  ./venv/bin/python thumb_backfill.py                      # unbounded (all missing), Ctrl-C safe

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:),
     THUMB_SERVICE_URL (default http://172.16.0.46:8090).
"""
import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from serve_publish import stage_manifest

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
GALLERY = REMOTE + "gallery"
SRC = REMOTE + "by-chat"
THUMBS = REMOTE + "thumbs"
THUMB_SERVICE_URL = os.environ.get("THUMB_SERVICE_URL", "http://172.16.0.46:8090")

# ─── Failure ledger (2026-10-08) ─────────────────────────────────────────────
# Some manifest items can NEVER produce a poster: protected/encrypted source
# media ffmpeg cannot decode, files larger than the cache filesystem, etc.
# Measured live before this existed: ~355 of every 400-item batch were the
# SAME permanently-failing stems, re-attempted every run for weeks — the
# batch spent ~35 minutes to produce ~40 real thumbnails. This ledger counts
# DETERMINISTIC failures per stem and skips a stem once it has failed
# FAIL_MAX times, until RETRY_AFTER_DAYS have passed since the last attempt
# (an automatic low-frequency safety net — a stem that becomes generatable
# again, e.g. one whose source finished uploading elsewhere, is retried
# without anyone remembering to run a flag). Only deterministic failures
# count (a 404 from the thumb endpoint carrying reason=deterministic is the
# HTTP-surface form of a decode-level verdict; a connection-refused while the
# service restarts must NOT poison the ledger). Entries self-clean: whenever
# a stem gains a thumbnail it is dropped, so the file never grows stale.
# Atomic writes (tmp+rename) so a kill mid-run cannot corrupt it.
FAIL_LEDGER = Path(os.environ.get("THUMB_FAIL_LEDGER", "/var/lib/media-gallery/thumb_backfill_failed.json"))
FAIL_MAX = int(os.environ.get("THUMB_FAIL_MAX", "3"))
RETRY_AFTER_DAYS = float(os.environ.get("THUMB_FAIL_RETRY_DAYS", "7"))
_ledger_lock = threading.Lock()


def load_fail_ledger() -> dict:
    try:
        d = json.loads(FAIL_LEDGER.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_fail_ledger(d: dict) -> None:
    try:
        FAIL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(FAIL_LEDGER) + ".tmp"
        Path(tmp).write_text(json.dumps(d, separators=(",", ":")))
        os.replace(tmp, FAIL_LEDGER)
    except OSError as e:
        log(f"fail-ledger save skipped: {e}")


def classify_failure(err: str) -> bool:
    """True when a thumb-generation failure should count toward the
    permanent-failure ledger. Only DETERMINISTIC failures count: a 404/410
    from the thumb endpoint is the HTTP-surface form of 'generation refused
    this stem' (decode-level/unavailable). A URLError (connection refused,
    timeout — e.g. the thumb service restarting mid-batch) or an HTTP 5xx is
    TRANSIENT and must never count, or a 20-second restart window would
    poison hundreds of healthy stems out of future batches."""
    if not err:
        return False
    if err.startswith("HTTP "):
        try:
            code = err.split()[1]
        except IndexError:
            return False
        return code in ("404", "410")       # gone / not generatable
    if err.startswith("HTTPError: HTTP Error 404") or err.startswith("HTTPError: HTTP Error 410"):
        return True
    if err.startswith("download failed") or err.startswith("thumb upload failed"):
        return False                          # rclone transport-level
    if err.startswith("empty") or "empty" in err:
        return False
    if err.startswith("make_thumb produced no output"):
        return True                           # decode produced nothing
    if err.startswith("URLError") or "Connection refused" in err:
        return False
    # Pillow/ffmpeg decode verdicts surface as their exception names
    if err.split(":")[0] in ("UnidentifiedImageError", "CalledProcessError",
                             "SyntaxError", "OSError"):
        return True
    return False


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def generate_thumb_local(chat, leaf, stem, work_dir):
    """Fast path for images (see the module's PERFORMANCE FIX docstring):
    download the original directly using the EXACT leaf filename the
    manifest already gave us (no find_original() folder listing needed),
    generate the thumbnail in-process via thumb_service.make_thumb() (same
    Pillow resize/quality settings the live service uses, imported directly
    so output is byte-for-byte consistent with what a real page-view would
    produce), and upload it to the encrypted Drive thumbs cache.

    Returns (ok: bool, bytes_downloaded: int, error: str | None).
    """
    import thumb_service  # local import: only needed on this path, and
    # importing it triggers a `from PIL import Image` + a LOCAL_CACHE mkdir
    # at module level -- fine for the real deploy (same venv/user as the
    # live thumb service) but no reason to pay that cost for --include-video
    # -only or --http-fallback runs that never call this function.
    tmp_src = work_dir / f"_src_{stem}_{leaf}"
    tmp_dst = work_dir / f"_dst_{stem}.jpg"
    try:
        r = rclone("copyto", f"{SRC}/{chat}/{leaf}", str(tmp_src))
        if r.returncode != 0:
            return False, 0, f"download failed: {r.stderr[:200]}"
        size = tmp_src.stat().st_size
        if size == 0:
            return False, 0, "downloaded original is empty"
        thumb_service.make_thumb(tmp_src, tmp_dst, False)
        if not tmp_dst.exists() or tmp_dst.stat().st_size == 0:
            return False, size, "make_thumb produced no output"
        r = rclone("copyto", str(tmp_dst), f"{THUMBS}/{chat}/{stem}.jpg")
        if r.returncode != 0:
            return False, size, f"thumb upload failed: {r.stderr[:200]}"
        return True, size, None
    except Exception as e:  # noqa: BLE001
        return False, 0, f"{type(e).__name__}: {e}"
    finally:
        for p in (tmp_src, tmp_dst):
            try:
                p.unlink()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=None,
                     help="max items to backfill this run (default: unbounded)")
    ap.add_argument("--delay", type=float, default=2.0,
                     help="seconds to sleep between requests (default: 2.0)")
    ap.add_argument("--include-video", action="store_true",
                     help="also backfill video posters. 2026-09-30: this is now "
                          "passed by the deployed background cron too — video "
                          "posters cost only a few MB via the HTTP-range path "
                          "(see thumb_service.py), vs a full-file download when "
                          "this flag was written off as too expensive.")
    ap.add_argument("--http-fallback", action="store_true",
                     help="force every item through thumb_service.py's live HTTP "
                          "endpoint (the original, slower implementation) instead "
                          "of the direct local generation path for images. Videos "
                          "always use this path regardless of this flag -- see the "
                          "PERFORMANCE FIX docstring for why. Use this only if the "
                          "fast local path is ever suspected of producing bad output.")
    ap.add_argument("--workers", type=int, default=4,
                     help="parallel HTTP workers for VIDEO posters (default: 4). "
                          "Videos are I/O-bound HTTP range fetches against the "
                          "local rclone serve; 4-way concurrency was measured "
                          "safe on gallery-01 (2 vCPU / 8GB) and cuts the "
                          "wall-clock of a video batch ~4x. Images keep their "
                          "serial local path + delay, which is a real "
                          "download/resize/upload round trip.")
    ap.add_argument("--retry-failed", action="store_true",
                     help="ignore the permanent-failure ledger and re-attempt "
                          "stems that previously failed %d times (default: skip "
                          "them). Use for the scheduled low-frequency retry sweep." % FAIL_MAX)
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="thumb_backfill_"))

    log("fetching manifest…")
    mp = work / "manifest.json"
    # Prefer the local tmpfs serve copy (instant); fall back to the Drive fetch.
    if not stage_manifest(mp, RCLONE_CONF, REMOTE, log=log):
        sys.exit(1)
    manifest = json.loads(mp.read_text())
    items = [it for it in manifest if args.include_video or it.get("type") != "video"]
    log(f"manifest items considered: {len(items)}")

    log("listing existing thumbnails on Drive (one pass, not per-item)…")
    r = rclone("lsf", "-R", "--files-only", THUMBS)
    if r.returncode != 0:
        log("cannot list thumbs:", r.stderr[:200])
        sys.exit(1)
    existing = set(r.stdout.splitlines())
    log(f"existing thumbnails: {len(existing)}")

    missing = [it for it in items
               if f"{it.get('chat') or ''}/{it['stem']}.jpg" not in existing]
    log(f"missing thumbnails: {len(missing)}")

    # Drop stems whose generation has already failed FAIL_MAX times in a row
    # (permanently un-generatable: protected/encrypted sources, oversized
    # files). Without this the batch spent ~90% of every run re-attempting
    # the same dead stems. Entries whose stem now HAS a thumb are dropped so
    # the ledger self-cleans; --retry-failed bypasses the filter entirely.
    fail_ledger = load_fail_ledger()
    now = time.time()
    for s in list(fail_ledger):
        if f"{s}.jpg" in existing:  # stem has a thumb now -> verdict obsolete
            fail_ledger.pop(s, None)

    def _skip_by_ledger(rec) -> bool:
        """True when this stem is in permanent-failure cooldown: it has hit
        FAIL_MAX deterministic failures AND its last attempt is more recent
        than RETRY_AFTER_DAYS. Older entries are retried automatically (the
        safety net), and entries below the threshold always are."""
        try:
            n, t = rec["n"], rec["t"]
        except (TypeError, KeyError):
            return False
        if n < FAIL_MAX:
            return False
        return (now - t) < RETRY_AFTER_DAYS * 86400

    if not args.retry_failed and fail_ledger:
        before = len(missing)
        missing = [it for it in missing
                   if not _skip_by_ledger(fail_ledger.get(f"{it.get('chat') or ''}/{it['stem']}"))]
        cooling = sum(1 for v in fail_ledger.values()
                      if isinstance(v, dict) and _skip_by_ledger(v))
        log(f"permanent-failure ledger: skipped {before - len(missing)} stems "
            f"({cooling} in cooldown, retried automatically after "
            f"{RETRY_AFTER_DAYS:g}d; --retry-failed to force now)")
    if args.retry_failed and fail_ledger:
        log(f"--retry-failed: ignoring {len(fail_ledger)} ledger entries this run")

    # 2026-09-30: process VIDEO posters FIRST. The manifest arrives newest
    # first, so the pre-fix order ground through images for days before it
    # ever reached the (previously 11.5K-strong) video backlog — which is
    # exactly why "thumbnail generation keeps being broken" was the lived
    # experience: the newest folders a user actually browses kept showing
    # blank video tiles while the repair queue worked on old images.
    # Videos are also the items users notice most (a missing photo poster
    # still shows SOMETHING; a missing video poster is a dead tile).
    missing.sort(key=lambda it: 0 if it.get("type") == "video" else 1)
    n_vid = sum(1 for it in missing if it.get("type") == "video")
    log(f"queue order: {n_vid} videos first, then {len(missing) - n_vid} images")

    if not missing:
        log("nothing to backfill — every item already has a thumbnail")
        return

    if args.budget is not None:
        missing = missing[:args.budget]
        log(f"budget={args.budget}: processing {len(missing)} this run")

    done = failed = 0
    bytes_seen = 0
    t0 = time.time()

    # Deterministic-failure counting for the permanent-failure ledger. Uses
    # the module-level classify_failure() (see its docstring for the
    # deterministic-vs-transient split, which is what keeps a service restart
    # from poisoning the ledger). Entries carry {n: count, t: last-attempt
    # epoch} so the cooldown check can retry stale verdicts automatically.
    def note_failure(chat: str, stem: str, err: str):
        if classify_failure(err):
            with _ledger_lock:
                k = f"{chat}/{stem}"
                rec = fail_ledger.get(k)
                n = (rec.get("n", 0) if isinstance(rec, dict) else 0) + 1
                fail_ledger[k] = {"n": n, "t": time.time()}
        return

    # ----- Phase 1: VIDEO posters, bounded parallel HTTP workers -----
    # These are I/O-bound range fetches against the local rclone serve (see
    # thumb_service.py), so N-way concurrency is the right shape and was
    # measured safe on gallery-01 at 4 (2 vCPU / 8GB; load stays ~2.2). The
    # service serializes per-stem work with its own locks and the tmpfs space
    # reservation keeps concurrent video fetches from overflowing RAM.
    video_items = [it for it in missing if it.get("type") == "video"]
    image_items = [it for it in missing if it.get("type") != "video"]
    counters = {"done": 0, "failed": 0, "bytes": 0}
    ctr_lock = threading.Lock()
    total = len(missing)
    finished = [0]

    def fetch_one(it):
        chat = it.get("chat") or ""
        stem = it["stem"]
        url = f"{THUMB_SERVICE_URL}/thumb/{chat}/{stem}.jpg"
        err = None
        nbytes = 0
        try:
            # 120s: a cold range read can be slow, and the old 60s cap
            # recorded those as failures.
            with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 — THUMB_SERVICE_URL is our own trusted internal http:// endpoint, not user input
                data = resp.read()
                nbytes = len(data)
                if resp.status != 200:
                    err = f"HTTP {resp.status}"
        except urllib.error.HTTPError as he:
            # The 404 carries X-Thumb-Reason: "deterministic" (decode-level —
            # worth remembering) or "transient" (retry later, never counted).
            # Fall back to the classic message when the header is absent
            # (older service build), where 404 is the deterministic signal.
            reason = (he.headers or {}).get("X-Thumb-Reason", "")
            if reason == "transient":
                err = f"URLError: transient 404 (reason=transient)"
            else:
                err = f"HTTPError: HTTP Error {he.code}: {he.reason}"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        with ctr_lock:
            finished[0] += 1
            counters["bytes"] += nbytes
            if err is None:
                counters["done"] += 1
                with _ledger_lock:
                    fail_ledger.pop(f"{chat}/{stem}", None)
            else:
                counters["failed"] += 1
                log(f"  [{finished[0]}/{total}] {chat}/{stem}: {err}")
                note_failure(chat, stem, err)
            if finished[0] % 25 == 0 or finished[0] == total:
                elapsed = time.time() - t0
                rate = finished[0] / elapsed if elapsed > 0 else 0
                eta_min = (total - finished[0]) / rate / 60 if rate > 0 else 0
                log(f"  progress: {finished[0]}/{total} "
                    f"({counters['done']} ok, {counters['failed']} failed), "
                    f"~{counters['bytes']/1024/1024:.0f} MB thumbnail data transferred, "
                    f"{rate:.2f}/s, ETA {eta_min:.0f} min")

    if video_items:
        workers = max(1, args.workers)
        log(f"phase 1: {len(video_items)} video poster(s), {workers} worker(s)")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(fetch_one, video_items))

    # ----- Phase 2: images, serial local path with throttle -----
    # Each image is a real download/resize/upload round trip through the shared
    # thumb-service HTTP endpoint; keep this serial + delayed as before.
    if image_items:
        log(f"phase 2: {len(image_items)} image(s), serial")
    for it in image_items:
        chat = it.get("chat") or ""
        stem = it["stem"]
        if args.http_fallback:
            # HTTP path for images too, but keep the serial + delay pacing and
            # count into the image counters (not the video phase counters).
            url = f"{THUMB_SERVICE_URL}/thumb/{chat}/{stem}.jpg"
            try:
                with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310
                    data = resp.read()
                    bytes_seen += len(data)
                    if resp.status == 200:
                        done += 1
                    else:
                        failed += 1
                        log(f"  {chat}/{stem}: HTTP {resp.status}")
                        note_failure(chat, stem, f"HTTP {resp.status}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                log(f"  {chat}/{stem}: {type(e).__name__}: {e}")
                note_failure(chat, stem, f"{type(e).__name__}: {e}")
        else:
            leaf = os.path.basename(it.get("file") or "")
            if not leaf:
                failed += 1
                log(f"  {chat}/{stem}: no 'file' field in manifest item")
                note_failure(chat, stem, "HTTP 404")  # unrecoverable metadata gap
            else:
                ok, size, err = generate_thumb_local(chat, leaf, stem, work)
                bytes_seen += size
                if ok:
                    done += 1
                    with _ledger_lock:
                        fail_ledger.pop(f"{chat}/{stem}", None)
                else:
                    failed += 1
                    log(f"  {chat}/{stem}: {err}")
                    note_failure(chat, stem, err or "unknown error")
        time.sleep(args.delay)

    done += counters["done"]
    failed += counters["failed"]
    bytes_seen += counters["bytes"]

    # Persist the failure ledger: stems past FAIL_MAX stay in cooldown and
    # are retried automatically after RETRY_AFTER_DAYS. Atomic write, so a
    # kill mid-batch can never corrupt it.
    try:
        trimmed = {k: v for k, v in fail_ledger.items()
                   if isinstance(v, dict) and v.get("n", 0) > 0}
        save_fail_ledger(trimmed)
        perm = sum(1 for v in trimmed.values() if v.get("n", 0) >= FAIL_MAX)
        log(f"failure ledger saved: {len(trimmed)} stems recorded, "
            f"{perm} at/over the {FAIL_MAX}x cooldown threshold")
    except Exception as e:  # noqa: BLE001
        log(f"failure ledger not saved: {e}")

    log(f"DONE: {done} generated, {failed} failed, "
        f"{time.time()-t0:.0f}s elapsed, {bytes_seen/1024/1024:.0f} MB")
    log("Re-run dedup_scan.py (or wait for the next hourly refresh) to pick "
        "these up into the duplicate report.")

    try:
        import shutil
        shutil.rmtree(work)
    except OSError:
        pass


if __name__ == "__main__":
    main()
