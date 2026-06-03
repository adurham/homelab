#!/usr/bin/env bash
# Auto-refresh the gallery: rebuild the date-sorted manifest from the current
# archive, then warm thumbnails for any new items. Driven by a systemd timer.
# Idempotent + cheap on a no-change run.
#
# SPLIT ARCHITECTURE: this box (the gallery platform) holds NO upstream source creds.
# Item dates are supplied by the collector at push time (recorded into the
# datemap by the upload service), and by EXIF/mtime for browser/bulk uploads.
# So build_manifest runs WITHOUT upstream source access — it just reads the datemap +
# archive listing. (build_manifest auto-detects absent creds and skips upstream source.)
set -uo pipefail

DIR=/opt/media-gallery
LOG=/var/log/media-gallery/refresh.log
export RCLONE_CONFIG=/home/mediaingest/.config/rclone/rclone.conf
export TG_RCLONE_REMOTE=gcrypt:

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== gallery refresh $(date -Is) ==="

# 1) rebuild manifest (no upstream source access; datemap + archive only)
"$DIR/venv/bin/python" "$DIR/build_manifest.py" || echo "manifest build failed"

# 2) warm thumbnails for any new items (skips cached)
bash "$DIR/prewarm_thumbs.sh" || echo "prewarm failed"

echo "=== refresh done $(date -Is) ==="
