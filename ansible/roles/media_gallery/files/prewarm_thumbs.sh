#!/usr/bin/env bash
# Background pre-warm: walk the manifest and request every thumbnail from the
# local thumb service so its cache (encrypted, on Drive) fills up. This is NOT
# a dependency — the gallery works without it; this just makes thumbnails
# instant instead of ~10s-cold. Safe to re-run; cached thumbs return fast.
#
# Runs at low concurrency to avoid hammering Drive / the single-proc service.
set -uo pipefail
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediaingest/.config/rclone/rclone.conf}"
THUMB_BASE="http://127.0.0.1:${THUMB_PORT:-8090}/thumb"
LOG="${PREWARM_LOG:-/var/log/media-gallery/prewarm.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== prewarm start $(date -Is) ==="

# Pull the manifest (decrypted) and extract chat/stem -> thumb paths.
MANIFEST=$(rclone --config "$RCLONE_CONF" cat gcrypt:gallery/manifest.json 2>/dev/null)
if [ -z "$MANIFEST" ]; then echo "no manifest, abort"; exit 0; fi

# Parse thumb paths with python (jq may be absent).
echo "$MANIFEST" | python3 -c '
import json,sys
for it in json.load(sys.stdin):
    t=it.get("thumb")
    if t: print(t)
' | while read -r thumb; do
  # thumb = thumb/<chat>/<stem>.jpg ; request it (generates+caches if missing)
  curl -s -o /dev/null --max-time 90 "http://127.0.0.1:${THUMB_PORT:-8090}/${thumb}"
done

echo "=== prewarm done $(date -Is) ==="
