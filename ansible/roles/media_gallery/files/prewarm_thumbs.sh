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
#
# 2026-09-30 — two changes:
#   * Run as its OWN systemd service+timer (media-gallery-prewarm), no longer
#     inside refresh_gallery.sh's flock. A multi-hour cold refill used to hold
#     the hourly refresh lock, so refreshes were SKIPPED for hours after every
#     reboot (host power events make this recurring here). Splitting them means
#     the manifest/dedup refresh keeps its cadence while the cache refills.
#   * RECENT-FIRST staged passes. A cold refill of ~266k thumbs is capped by
#     the Drive API rate pacer (~10 files/s) to a ~7 hour job, during which the
#     gallery serves cold (2.5s/small photo, ~20s/video) thumbnails. Copying
#     the most RECENT thumbnails first restores the folders actually being
#     browsed within minutes. Stage 1 is a strict 14-day window; later passes
#     widen it, then a final full sweep catches anything the windows missed
#     (each pass skips what is already local, so the cost is one extra listing
#     walk per stage, not re-copies).
set -uo pipefail
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediagallery/.config/rclone/rclone.conf}"
THUMB_LOCAL_CACHE="${THUMB_LOCAL_CACHE:-/var/lib/media-gallery/thumbcache}"
TRANSFERS="${PREWARM_TRANSFERS:-16}"
LOG="${PREWARM_LOG:-/var/log/media-gallery/prewarm.log}"
SRC="${TG_RCLONE_REMOTE:-gcrypt:}thumbs/"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== prewarm start $(date -Is) ==="

if ! mountpoint -q "$THUMB_LOCAL_CACHE"; then
  echo "thumbcache $THUMB_LOCAL_CACHE is not an active mount — refusing to warm"
  exit 1
fi

copy_pass() {
  local label="$1"; shift
  echo "--- prewarm pass: $label"
  rclone --config "$RCLONE_CONF" copy "$SRC" "$THUMB_LOCAL_CACHE/" \
    --order-by modtime,descending \
    --transfers="$TRANSFERS" --checkers="$TRANSFERS" \
    --stats=5m --stats-one-line "$@" \
    || echo "prewarm pass '$label' reported errors (non-fatal — thumb service still works via on-the-fly fallback)"
}

# Stage 1: recent content first (fast win for what is actually being browsed).
copy_pass "recent 14d" --max-age 14d
# Stage 2+3: widen the window before the final full sweep.
copy_pass "recent 90d" --max-age 90d
copy_pass "full sweep"
echo "=== prewarm done $(date -Is) (thumbcache files: $(find "$THUMB_LOCAL_CACHE" -type f 2>/dev/null | wc -l)) ==="
