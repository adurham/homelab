#!/usr/bin/env bash
# VictoriaMetrics YEARLY archive - pushes the full local dataset to the
# GDrive cold tier (archive-yearly/) before it rolls off the 2y local retention.
#
# Runs via systemd timer (victoriametrics-archive-yearly.timer) on Jan 1 04:00.
# Keeps the yearly snapshot forever (or until manually pruned).
#
# This is the "cold tier": data >2y old is ONLY restorable from this archive.
# To query archived data: restore a yearly snapshot to a scratch VM instance.
# See docs/vm-backup-restore.md for the restore procedure.

set -euo pipefail
VM_URL="http://localhost:8428"
RCLONE="/usr/bin/rclone"
RCLONE_CONF="/root/.config/rclone/rclone.conf"
REMOTE_ARCHIVE="vmbackup_crypt:archive-yearly"
STATE_DIR="{{ vm_backup_state_dir }}"
LOG_TAG="vm-archive-yearly"

mkdir -p "$STATE_DIR"
log() { logger -t "$LOG_TAG" -- "$*"; echo "[$(date -Is)] $*" >&2; }

YEAR=$(date -u +%Y)
DEST="$REMOTE_ARCHIVE/$YEAR"

# Idempotent: if this year's archive already exists, skip
if $RCLONE --config "$RCLONE_CONF" lsd "$DEST" >/dev/null 2>&1; then
  log "Archive $DEST already exists - skipping (idempotent)"
  exit 0
fi

# --- 1. Create VM snapshot ---
SNAP_RESP=$(curl -fsS -X POST "$VM_URL/snapshot/create") || {
  log "ERROR: snapshot/create failed"; exit 1
}
SNAP_NAME=$(echo "$SNAP_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["snapshot"])' 2>/dev/null || echo "")
[ -n "$SNAP_NAME" ] || { log "ERROR: could not parse snapshot name: $SNAP_RESP"; exit 1; }
SNAP_PATH="/var/lib/victoria-metrics/snapshots/$SNAP_NAME"
log "Created snapshot: $SNAP_NAME"

# --- 2. Upload to archive-yearly/<year> (-L dereferences symlinks; see daily script) ---
log "Uploading full dataset -> $DEST"
if ! $RCLONE --config "$RCLONE_CONF" copy -L "$SNAP_PATH/" "$DEST/" \
    --transfers 4 --stats=30s --stats-one-line 2>&1 | logger -t "$LOG_TAG"; then
  log "ERROR: rclone copy failed for yearly archive $SNAP_NAME"
  exit 2
fi

# --- 3. Verify + cleanup ---
$RCLONE --config "$RCLONE_CONF" lsd "$DEST" >/dev/null 2>&1 || {
  log "ERROR: archive $DEST not found after upload"; exit 3
}
log "Verified: $DEST exists on GDrive"

curl -fsS -X POST "$VM_URL/snapshot/delete?snapshot=$SNAP_NAME" >/dev/null || \
  log "WARN: could not delete local snapshot $SNAP_NAME"

echo "$YEAR" > "$STATE_DIR/last_archive_year"
log "Yearly archive complete: $DEST"