#!/usr/bin/env bash
# Encrypt + ship captured media to Google Drive via rclone crypt, then prune
# the local cache. Driven by a systemd timer (see sync.timer).
#
# Pipeline:
#   1. rclone copy SAVE_DIR -> gcrypt:   (client-side encrypted upload;
#      filenames + contents are encrypted before they leave the box)
#   2. verify the remote has each file (rclone check), then delete locals
#      OLDER than CACHE_DAYS — recent captures stay local for fast access.
#
# rclone config lives at /home/mediaingest/.config/rclone/rclone.conf and
# defines two remotes:
#   gdrive:  the raw Google Drive remote (OAuth token)
#   gcrypt:  crypt remote wrapping gdrive:media-gallery  (the encryption layer)
#
# Idempotent and safe to run on an empty dir.
set -euo pipefail

SAVE_DIR="${TG_SAVE_DIR:-/var/lib/media-gallery/captures}"
REMOTE="${TG_RCLONE_REMOTE:-gcrypt:}"
CACHE_DAYS="${TG_CACHE_DAYS:-7}"
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediaingest/.config/rclone/rclone.conf}"
LOG="${INGEST_LOG:-/var/log/media-gallery/sync.log}"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== sync run $(date -Is) ==="

shopt -s nullglob
files=("$SAVE_DIR"/*)
if [ ${#files[@]} -eq 0 ]; then
  echo "no files to sync"
  exit 0
fi

# 1) upload (encrypted). copy (not move) so we control pruning by age below.
rclone --config "$RCLONE_CONF" copy "$SAVE_DIR" "$REMOTE" \
  --transfers 4 --checkers 8 --log-level INFO

# 2) verify everything landed, then prune locals older than CACHE_DAYS.
#    rclone check exits non-zero if anything differs; -e stops us pruning
#    on a failed/partial upload.
rclone --config "$RCLONE_CONF" check "$SAVE_DIR" "$REMOTE" --one-way

echo "upload verified; pruning local files older than ${CACHE_DAYS}d"
find "$SAVE_DIR" -type f -mtime +"$CACHE_DAYS" -print -delete

echo "=== sync done $(date -Is) ==="
