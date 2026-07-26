#!/usr/bin/env bash
# VictoriaMetrics daily snapshot + encrypted GDrive backup.
# Runs via systemd timer (victoriametrics-backup.timer).
#
# Flow:
#   1. POST /snapshot/create on local VM -> creates consistent snapshot dir
#   2. rclone copy -L snapshot -> vmbackup_crypt:daily/<date> (encrypted, GDrive)
#      (-L dereferences symlinks: VM snapshots use symlinks for data/big,
#       data/small, data/indexdb pointing back into the live data dir;
#       without -L rclone silently skips them and you get an 8-byte useless backup.)
#   3. On success: DELETE local snapshot, prune GDrive daily/ to 90 days
#   4. On failure: leave local snapshot, log to stderr + journal, exit non-zero
#
# Tiering: data older than 2y rolls off local VM per -retentionPeriod=2y.
# A SEPARATE yearly job (victoriametrics-archive-yearly.service) snapshots the
# full local dataset to vmbackup_crypt:archive-yearly/ before that rolloff.
# That is the cold tier the user can restore from.

set -euo pipefail
VM_URL="http://localhost:8428"
RCLONE="/usr/bin/rclone"
RCLONE_CONF="/root/.config/rclone/rclone.conf"
REMOTE_DAILY="vmbackup_crypt:daily"
STATE_DIR="{{ vm_backup_state_dir }}"
LOG_TAG="vm-backup"
RETENTION_DAYS={{ vm_backup_daily_retention_days }}

mkdir -p "$STATE_DIR"

log() { logger -t "$LOG_TAG" -- "$*"; echo "[$(date -Is)] $*" >&2; }

# --- 1. Create VM snapshot ---
SNAP_RESP=$(curl -fsS -X POST "$VM_URL/snapshot/create") || {
  log "ERROR: snapshot/create failed"
  exit 1
}
SNAP_NAME=$(echo "$SNAP_RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["snapshot"])' 2>/dev/null || echo "")
if [ -z "$SNAP_NAME" ]; then
  log "ERROR: could not parse snapshot name from response: $SNAP_RESP"
  exit 1
fi
SNAP_PATH="/var/lib/victoria-metrics/snapshots/$SNAP_NAME"
log "Created snapshot: $SNAP_NAME"
[ -d "$SNAP_PATH" ] || { log "ERROR: snapshot path $SNAP_PATH does not exist"; exit 1; }

# --- 2. Upload to GDrive (encrypted, dereferencing symlinks) ---
DEST="$REMOTE_DAILY/$(date -u +%Y%m%dT%H%M%SZ)"
log "Uploading $SNAP_PATH -> $DEST"
if ! $RCLONE --config "$RCLONE_CONF" copy -L "$SNAP_PATH/" "$DEST/" --transfers 4 --stats=10s --stats-one-line 2>&1 | logger -t "$LOG_TAG"; then
  log "ERROR: rclone copy failed for $SNAP_NAME"
  exit 2
fi
log "Upload complete: $DEST"

# --- 3. Verify upload by listing the dest ---
if ! $RCLONE --config "$RCLONE_CONF" lsd "$DEST" >/dev/null 2>&1; then
  log "ERROR: uploaded destination $DEST not found - rclone may have silently failed"
  exit 3
fi
log "Verified: $DEST exists on GDrive"

# --- 4. Delete local snapshot ---
if curl -fsS -X POST "$VM_URL/snapshot/delete?snapshot=$SNAP_NAME" >/dev/null; then
  log "Deleted local snapshot $SNAP_NAME"
else
  log "WARN: could not delete local snapshot $SNAP_NAME (disk will accumulate)"
fi

# --- 5. Prune GDrive daily/ older than RETENTION_DAYS ---
log "Pruning GDrive daily/ snapshots older than $RETENTION_DAYS days"
$RCLONE --config "$RCLONE_CONF" delete "$REMOTE_DAILY" \
  --min-age "${RETENTION_DAYS}d" --rmdirs 2>&1 | logger -t "$LOG_TAG" || true

# --- 6. Touch state file for healthcheck ---
date -u +%s > "$STATE_DIR/last_success"
log "Backup complete: $DEST"