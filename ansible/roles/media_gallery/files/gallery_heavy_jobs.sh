#!/usr/bin/env bash
# Sequential heavy-job runner for the gallery CT (2026-10-01).
#
# WHY SEQUENTIAL: running the reclaim + video-dedupe sweep + spam OCR scan at
# the same time pushed this 2-vCPU / 8GB CT to load 32 and 100% swap (measured
# live). Each job is CPU-or-memory heavy in its own way, so they run ONE AT A
# TIME here, with a health gate between them.
#
# Each stage is idempotent / resumable:
#   - reclaim_hidden    : already-deleted stems simply skip
#   - dedup_videos      : verification cache means only NEW videos are hashed
#   - spam_scan         : OCR verdicts are cached per stem
# so a crash, reboot, or manual kill loses at most the current item.
#
# Usage: gallery_heavy_jobs.sh [stage]   (no stage = run all, in order)
set -uo pipefail
DIR=/opt/media-gallery
PY="$DIR/venv/bin/python"
LOG=/var/log/media-gallery/heavy_jobs.log
RCLONE_CONF=/home/mediagallery/.config/rclone/rclone.conf
export RCLONE_CONFIG="$RCLONE_CONF"
export TG_RCLONE_REMOTE=gcrypt:

exec >>"$LOG" 2>&1

# Defense-in-depth against two runners overlapping (systemd already serializes
# same-unit runs, but a manual invocation during a timer run must not double
# the Drive delete load). -n = fail fast; the timer will re-fire later.
exec 9>/var/lock/media-gallery-heavy-jobs.lock
if ! flock -n 9; then
  echo "=== heavy jobs $(date -Is): SKIPPED, another run in progress ==="
  exit 0
fi

echo "=== heavy jobs start $(date -Is) (stage=${1:-all}) ==="

# ---- health gate: wait for the CT to be comfortable before each stage ----
wait_healthy() {
  local tries=0
  while [ $tries -lt 60 ]; do
    # available memory above ~800MB and load under 6 (2 vCPUs)
    local avail load
    avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    load=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
    if [ "${avail:-0}" -gt 800 ] && [ "${load:-99}" -lt 6 ]; then
      return 0
    fi
    echo "  waiting for headroom (avail=${avail}MB load=${load})"
    sleep 20; tries=$((tries+1))
  done
  echo "  health gate timed out — proceeding anyway"
  return 0
}

run_reclaim() {
  echo "--- stage: reclaim hidden duplicates $(date -Is)"
  sudo -u mediagallery "$PY" "$DIR/reclaim_hidden.py" --apply --batch 400 --pause 0.5 \
    || echo "reclaim exited non-zero (resumable — re-run continues)"
}

run_video_dedup() {
  echo "--- stage: video dedupe verification sweep $(date -Is)"
  # high cap = verify everything pending; the cache keeps re-runs cheap
  sudo -u mediagallery env DEDUP_VIDEO_MAX_VERIFY=50000 "$PY" "$DIR/dedup_videos.py" \
    || echo "video sweep exited non-zero (resumable)"
}

run_spam_scan() {
  echo "--- stage: spam OCR scan $(date -Is)"
  # budget high; the per-stem OCR cache makes re-runs incremental
  sudo -u mediagallery "$PY" "$DIR/spam_scan.py" --budget 200000 \
    || echo "spam scan exited non-zero (resumable)"
}

case "${1:-all}" in
  reclaim)    wait_healthy; run_reclaim ;;
  video)      wait_healthy; run_video_dedup ;;
  spam)       wait_healthy; run_spam_scan ;;
  all)
    wait_healthy; run_reclaim
    wait_healthy; run_video_dedup
    wait_healthy; run_spam_scan
    ;;
  *) echo "unknown stage: $1"; exit 2 ;;
esac
echo "=== heavy jobs done $(date -Is) ==="
