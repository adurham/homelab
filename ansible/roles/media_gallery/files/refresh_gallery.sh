#!/usr/bin/env bash
# Auto-refresh the gallery: rebuild the date-sorted manifest from the current
# archive, warm thumbnails for any new items, then update the duplicate report
# incrementally. Driven by a systemd timer. Idempotent + cheap on a no-change run.
#
# SPLIT ARCHITECTURE: this box (the gallery platform) holds NO upstream source creds.
# Item dates are supplied by the collector at push time (recorded into the
# datemap by the upload service), and by EXIF/mtime for browser/bulk uploads.
# So build_manifest runs WITHOUT upstream source access — it just reads the datemap +
# archive listing. (build_manifest auto-detects absent creds and skips upstream source.)
#
# DEDUP SCAN NOW RUNS HERE TOO (2026-09-12): previously dedup_scan.py only ran
# on-demand via a manual "Scan now" button in the UI, and its v1 implementation
# took ~90 minutes for ~130k items (full re-hash + O(n^2) comparison every
# time) -- far too slow to put on an hourly timer. It sat unrun for 3+ months
# in practice: a real user complaint ("the built-in dedupe just doesn't work")
# turned out to be exactly this -- a report so stale it no longer reflected
# either new duplicates OR items already deleted weeks earlier. dedup_scan.py
# v2 is incremental (only hashes genuinely new stems, cached hashes reused
# forever) and uses LSH banding instead of brute-force comparison, so a
# steady-state run costs seconds, not an hour -- cheap enough to chain onto
# this same hourly refresh unconditionally.
set -uo pipefail

DIR=/opt/media-gallery
LOG=/var/log/media-gallery/refresh.log
LOCK=/var/lock/media-gallery-refresh.lock
export RCLONE_CONFIG=/home/mediagallery/.config/rclone/rclone.conf
export TG_RCLONE_REMOTE=gcrypt:

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

# systemd's Type=oneshot already serializes normal timer-driven runs of THIS
# unit -- but flock here too as defense-in-depth against an ad-hoc manual
# invocation (e.g. `python dedup_scan.py` run by hand for a one-off check)
# overlapping a timer-triggered run and racing on dedup_hash_cache.json /
# dedup.json. Demonstrated live 2026-09-12: a manual foreground test of
# dedup_scan.py collided with the hourly timer mid-development. -n = fail
# fast (don't queue up a pile of waiting runs) rather than block.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "=== gallery refresh $(date -Is): SKIPPED, another run already in progress ==="
  exit 0
fi

echo "=== gallery refresh $(date -Is) ==="

# 1) rebuild manifest (no upstream source access; datemap + archive only)
"$DIR/venv/bin/python" "$DIR/build_manifest.py" || echo "manifest build failed"

# 2) warm thumbnails for any new items (skips cached)
bash "$DIR/prewarm_thumbs.sh" || echo "prewarm failed"

# 3) incremental duplicate-report refresh (only hashes new items; see
# dedup_scan.py's module docstring for the incremental + LSH-banding design
# that makes this safe to run every hour instead of only on manual demand)
"$DIR/venv/bin/python" "$DIR/dedup_scan.py" || echo "dedup scan failed"

echo "=== refresh done $(date -Is) ==="

