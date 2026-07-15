#!/usr/bin/env bash
# Watchdog: alert if VM backup hasn't succeeded recently.
# Runs via systemd timer (victoriametrics-backup-watchdog.timer) every 6h.
# Writes to syslog/journal with tag vm-backup-watchdog; pairs with disk-watchdog.
set -euo pipefail
STATE_FILE="{{ vm_backup_state_dir }}/last_success"
THRESHOLD_S=$((36 * 3600))
NOW=$(date -u +%s)
LOG_TAG="vm-backup-watchdog"

if [ ! -f "$STATE_FILE" ]; then
  echo "[$(date -Is)] CRITICAL: no successful VM backup yet (state file $STATE_FILE missing)" >&2
  logger -t "$LOG_TAG" -p user.err "CRITICAL: no successful VM backup yet"
  exit 1
fi
AGE=$((NOW - $(cat "$STATE_FILE")))
if [ "$AGE" -ge "$THRESHOLD_S" ]; then
  echo "[$(date -Is)] CRITICAL: last VM backup was $((AGE/3600))h ago (> ${THRESHOLD_S/3600}h threshold)" >&2
  logger -t "$LOG_TAG" -p user.err "CRITICAL: last VM backup $((AGE/3600))h ago (threshold ${THRESHOLD_S/3600}h)"
  exit 1
fi
logger -t "$LOG_TAG" "OK: last VM backup $((AGE/3600))h ago"
echo "[$(date -Is)] OK: last VM backup $((AGE/3600))h ago"