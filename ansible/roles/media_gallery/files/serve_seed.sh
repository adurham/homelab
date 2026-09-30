#!/usr/bin/env bash
# Seed the LOCAL tmpfs serve dir (media-gallery-serve.service, port 8093) from
# the encrypted Drive copy of the gallery metadata files.
#
# WHY: the SPA's page load fetches manifest.json (~85MB uncompressed today).
# Serving those files from the local RAM tmpfs instead of streaming them from
# Google Drive through `rclone serve http gcrypt:` cut a cold page-load
# metadata fetch from ~10s to ~0.2s (measured 2026-09-30). The tmpfs does not
# survive a reboot, so this script refills it right after boot (systemd
# media-gallery-serve-seed.service) and is safe to re-run any time.
#
# SAFETY: refuses to write unless the target is an active mount point, so the
# decrypted metadata can never silently land on the CT's disk when the tmpfs
# is down. rclone copy skips files that already match, so re-runs are cheap.
#
# NOT a hard dependency: if this fails, lb-01's nginx falls back to the
# Drive-backed server for these paths (slow but working). Never fatal.
set -uo pipefail
RCLONE_CONF="${RCLONE_CONFIG:-/home/mediagallery/.config/rclone/rclone.conf}"
SERVE_DIR="${TG_SERVE_DIR:-/var/lib/media-gallery/serve}"
GALLERY_REMOTE="${TG_RCLONE_REMOTE:-gcrypt:}gallery/"
LOG="${SERVE_SEED_LOG:-/var/log/media-gallery/serve_seed.log}"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== serve seed start $(date -Is) ==="

if ! mountpoint -q "$SERVE_DIR"; then
  echo "serve dir $SERVE_DIR is not an active mount — refusing to seed"
  exit 1
fi

mkdir -p "$SERVE_DIR/gallery"

# Only the files the SPA actually fetches over HTTP. hidden.json / folder_meta
# / excluded.json are read server-side via rclone, never by the browser.
LIST="$(mktemp)"
trap 'rm -f "$LIST"' EXIT
printf 'index.html\nmanifest.json\nfolders.json\ndedup.json\n' >"$LIST"

rclone --config "$RCLONE_CONF" copy "$GALLERY_REMOTE" "$SERVE_DIR/gallery/" \
  --files-from "$LIST" --transfers 4 --checkers 4 --stats=0 \
  || echo "seed copy reported errors (non-fatal — nginx falls back to the Drive-backed path)"

ls -la "$SERVE_DIR/gallery/" 2>/dev/null
echo "=== serve seed done $(date -Is) ==="
