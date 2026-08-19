#!/usr/bin/env bash
# Pre-warm the RAM tmpfs thumbnail cache from the PERSISTENT encrypted Drive
# cache (gcrypt:thumbs/) via a bulk `rclone copy`. NOT a dependency — the
# gallery works without it via the thumb service's on-the-fly fallback; this
# just makes thumbnails instant instead of ~2.5s cold.
#
# HISTORY / WHY BULK COPY (2026-08-19): the original approach hit the thumb
# service's HTTP endpoint one file at a time (`xargs -P 6 curl ...`), reusing
# the same code path a live cold request takes. That path's per-file latency
# (~2.5s: check Drive-cache -> miss/hit -> ffmpeg/Pillow -> re-upload) makes a
# full cold rebuild take DAYS for ~130k thumbnails. After a reboot wipes the
# RAM tmpfs, every hourly refresh_gallery.sh run restarted from zero, always
# losing the race against the service's TimeoutStartSec and getting killed —
# an infinite retry-from-scratch loop that never actually recovered.
#
# The persistent gcrypt:thumbs/ cache (see thumb_service.py's read-through
# design) is already ~98% populated in steady state — a reboot only wipes the
# LOCAL tmpfs mirror, not the source of truth on Drive. A single bulk `rclone
# copy` restores the whole tmpfs from that already-encrypted cache with real
# parallelism (~20x+ faster in practice than the old per-file HTTP loop) and
# is safe to interrupt/resume: rclone skips files that already match at the
# destination, so a partial run followed by another `rclone copy` just picks
# up where it left off — no wasted work.
#
# IMPORTANT: hit rclone directly (gcrypt:thumbs/ -> local tmpfs), NOT the
# thumb service's HTTP endpoint. --transfers/--checkers bound below to avoid
# hammering the Drive API from a cold start (individual accounts can hit
# per-user rate limits well before this box's own bandwidth caps).
set -uo pipefail
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediagallery/.config/rclone/rclone.conf}"
THUMB_LOCAL_CACHE="${THUMB_LOCAL_CACHE:-/var/lib/media-gallery/thumbcache}"
TRANSFERS="${PREWARM_TRANSFERS:-16}"
LOG="${PREWARM_LOG:-/var/log/media-gallery/prewarm.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== prewarm start $(date -Is) ==="

rclone --config "$RCLONE_CONF" copy gcrypt:thumbs/ "$THUMB_LOCAL_CACHE/" \
  --transfers="$TRANSFERS" --checkers="$TRANSFERS" \
  --stats=5m --stats-one-line \
  || echo "prewarm bulk copy failed (non-fatal — thumb service still works via on-the-fly fallback)"

echo "=== prewarm done $(date -Is) ==="
