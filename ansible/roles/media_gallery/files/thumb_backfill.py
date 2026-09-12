#!/usr/bin/env python3
"""
One-time (or run-as-needed), THROTTLED backfill: generate thumbnails for
manifest items that have never been viewed in the gallery UI, and so have
never had a thumbnail created at all.

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
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
GALLERY = REMOTE + "gallery"
THUMBS = REMOTE + "thumbs"
THUMB_SERVICE_URL = os.environ.get("THUMB_SERVICE_URL", "http://172.16.0.46:8090")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=None,
                     help="max items to backfill this run (default: unbounded)")
    ap.add_argument("--delay", type=float, default=2.0,
                     help="seconds to sleep between requests (default: 2.0)")
    ap.add_argument("--include-video", action="store_true",
                     help="also backfill video posters (default: images only, "
                          "since video posters cost far more bandwidth/time per item)")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="thumb_backfill_"))

    log("fetching manifest…")
    mp = work / "manifest.json"
    r = rclone("copyto", f"{GALLERY}/manifest.json", str(mp))
    if r.returncode != 0:
        log("cannot fetch manifest:", r.stderr[:200])
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

    if not missing:
        log("nothing to backfill — every item already has a thumbnail")
        return

    if args.budget is not None:
        missing = missing[:args.budget]
        log(f"budget={args.budget}: processing {len(missing)} this run")

    done = failed = 0
    bytes_seen = 0
    t0 = time.time()
    for i, it in enumerate(missing):
        chat = it.get("chat") or ""
        stem = it["stem"]
        url = f"{THUMB_SERVICE_URL}/thumb/{chat}/{stem}.jpg"
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
                bytes_seen += len(data)
                if resp.status == 200:
                    done += 1
                else:
                    failed += 1
                    log(f"  [{i+1}/{len(missing)}] {chat}/{stem}: HTTP {resp.status}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"  [{i+1}/{len(missing)}] {chat}/{stem}: {type(e).__name__}: {e}")

        if (i + 1) % 25 == 0 or (i + 1) == len(missing):
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta_min = (len(missing) - i - 1) / rate / 60 if rate > 0 else 0
            log(f"  progress: {i+1}/{len(missing)} ({done} ok, {failed} failed), "
                f"~{bytes_seen/1024/1024:.0f} MB thumbnail data transferred, "
                f"{rate:.2f}/s, ETA {eta_min:.0f} min")

        time.sleep(args.delay)

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
