#!/usr/bin/env bash
# Set a Dell BIOS attribute via the dell-wmi-sysman sysfs interface,
# prompting for the BIOS admin password (required whenever one is set).
#
# Primary use case: flipping AC Recovery to "On" on the Proxmox nodes so
# they boot themselves after a power loss.
#
#   usage: dell-set-ac-recovery-on.sh [attribute] [value]
#   defaults: AcPwrRcvry On
#
# WHY A PROMPT: when a BIOS admin password is configured, every attribute
# write fails with "Operation not supported" and dmesg shows
# "admin password must be configured"; supplying a WRONG password instead
# gives dmesg "invalid password". Prime authentication/Admin/current_password
# with the real password for the call, then clear the kernel-side buffer.
# The password is read silently, never echoed, never written to disk.
set -euo pipefail

ATTR_NAME="${1:-AcPwrRcvry}"
ATTR_VALUE="${2:-On}"
BASE=/sys/class/firmware-attributes/dell-wmi-sysman
ATTR="$BASE/attributes/$ATTR_NAME/current_value"
AUTH="$BASE/authentication/Admin/current_password"

[ -e "$ATTR" ] || { echo "ERROR: $ATTR not found (no dell-wmi-sysman interface?)" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "ERROR: must run as root" >&2; exit 1; }

echo "attribute: $ATTR_NAME"
echo "current:   $(cat "$ATTR")"
echo "target:    $ATTR_VALUE"

read -r -s -p "BIOS admin password (leave blank if none is set): " PW
echo

cleanup() {
  printf '%s' "" > "$AUTH" 2>/dev/null || true
  PW=""
}
trap cleanup EXIT

printf '%s' "$PW" > "$AUTH"

ERRFILE="$(mktemp /run/dell-attr-write.XXXXXX.err)"
if ! printf '%s' "$ATTR_VALUE" > "$ATTR" 2>"$ERRFILE"; then
  echo "WRITE FAILED: $(cat "$ERRFILE")" >&2
  echo "recent dmesg:" >&2
  dmesg | tail -3 >&2
  rm -f "$ERRFILE"
  exit 2
fi
rm -f "$ERRFILE"

sleep 1
after="$(cat "$ATTR")"
echo "readback:  $after"
if [ "$after" = "$ATTR_VALUE" ]; then
  echo "OK: $ATTR_NAME is now $ATTR_VALUE"
else
  echo "WARNING: readback is '$after', expected '$ATTR_VALUE' — check 'dmesg | tail'" >&2
  exit 3
fi
