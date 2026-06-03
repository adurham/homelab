#!/usr/bin/env bash
# Auto-refresh the gallery: rebuild the date-sorted manifest from the current
# archive, then warm thumbnails for any new items. Driven by a systemd timer.
# Idempotent + cheap on a no-change run (manifest rebuild is seconds; prewarm
# skips already-cached thumbs). Keeps the gallery current as the live collector
# captures new media — no manual step needed.
set -uo pipefail

DIR=/opt/media-gallery
LOG=/var/log/media-gallery/refresh.log
export RCLONE_CONFIG=/home/mediaingest/.config/rclone/rclone.conf
export TG_RCLONE_REMOTE=gcrypt:
export TG_SESSION=/var/lib/media-gallery/galmeta

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== gallery refresh $(date -Is) ==="

# upstream source API creds come from the collector env (vault-rendered).
# shellcheck disable=SC1091
set -a; . "$DIR/collector.env"; set +a
export TG_API_ID="$TG_API_ID" TG_API_HASH="$TG_API_HASH"

# 1) rebuild manifest (fast)
"$DIR/venv/bin/python" "$DIR/build_manifest.py" || echo "manifest build failed"

# 2) warm thumbnails for any new items (skips cached)
bash "$DIR/prewarm_thumbs.sh" || echo "prewarm failed"

echo "=== refresh done $(date -Is) ==="
