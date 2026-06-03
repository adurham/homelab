#!/usr/bin/env bash
# Background pre-warm: walk the manifest and request every thumbnail from the
# thumb service so its tmpfs (RAM) cache fills. NOT a dependency — the gallery
# works without it via on-the-fly fallback; this just makes thumbnails instant
# instead of ~2.5s cold (pulled from the encrypted Drive cache into tmpfs).
#
# IMPORTANT: hit the thumb service on its real bind address (the CT's private
# IP, NOT localhost — the service binds 172.16.0.51 so nginx can reach it).
# Low concurrency to avoid hammering Drive / the service.
set -uo pipefail
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediaingest/.config/rclone/rclone.conf}"
THUMB_HOST="${THUMB_HOST:-172.16.0.51}"
THUMB_PORT="${THUMB_PORT:-8090}"
LOG="${PREWARM_LOG:-/var/log/media-gallery/prewarm.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== prewarm start $(date -Is) ==="

MANIFEST=$(rclone --config "$RCLONE_CONF" cat gcrypt:gallery/manifest.json 2>/dev/null)
[ -z "$MANIFEST" ] && { echo "no manifest"; exit 0; }

echo "$MANIFEST" | python3 -c 'import json,sys
for it in json.load(sys.stdin):
    t=it.get("thumb")
    if t: print(t)' | \
  xargs -P 6 -I{} curl -s -o /dev/null --max-time 120 "http://${THUMB_HOST}:${THUMB_PORT}/{}"

echo "=== prewarm done $(date -Is) ==="
