#!/bin/bash
# vnc_click.sh <vmid> <node> <local_port> <x> <y>
#
# Sends a single left-click at (x,y) on a VM's Proxmox VNC console, then
# exits. Built specifically to automate dismissing the Windows Server
# 2022 OOBE "It's time to enter the product key" screen -- see
# tanium_windows_vm_clone's OOBE-wait task header for why this exists:
# the win-server-2022 template's sysprep was run with NO unattend.xml,
# so it carries no embedded ProductKey, and every fresh clone stops on
# this screen until "Do this later" is clicked. The correct long-term
# fix is baking a KMS client key into the template's answer file (see
# docs/windows_template_guide.md) -- this script is the interim,
# fully-scriptable workaround so the playbook doesn't need a human at
# a VNC console for every single fresh clone in the meantime.
#
# Harmless to run against a VM that ISN'T on this screen -- clicking
# an arbitrary desktop/lock-screen coordinate does nothing observable.
# Requires: python3 with `websockets` installed, and vncdotool's
# `vncdo` on PATH (both already used elsewhere in this session for the
# same VNC-bridge technique).
set -uo pipefail
VMID="$1"; NODE="$2"; PORT="$3"; X="$4"; Y="$5"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PWFILE="/tmp/vnc_click_pw_${VMID}.txt"
LOGFILE="/tmp/vnc_click_bridge_${VMID}.log"
VNCDO="${VNCDO_BIN:-/Library/Frameworks/Python.framework/Versions/3.13/bin/vncdo}"
PY="${PYTHON_BIN:-$HOME/.pyenv/versions/3.12.12/bin/python3}"
CMDFILE="/tmp/vnc_click_cmd_${VMID}.txt"

# Same credentials file used by every other Proxmox-API script this
# session (pve_exec.sh, vnc_run.sh) -- required by pve_vnc_bridge.py
# for PVE_API/PVE_AUTH. Not committed to the repo (real credentials);
# this script fails loudly if it's missing rather than silently
# proceeding with an unauthenticated bridge.
PVE_ENV_FILE="${PVE_ENV_FILE:-$HOME/.config/proxmox-lab/env}"
if [ ! -f "$PVE_ENV_FILE" ]; then
  echo "vnc_click.sh: missing $PVE_ENV_FILE (PVE_API/PVE_AUTH credentials) -- cannot proceed" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$PVE_ENV_FILE"

cat > "$CMDFILE" << EOF
key ctrl-alt-del
pause 3
move ${X} ${Y}
click 1
pause 1
EOF

for cycle in 1 2 3; do
  pkill -f "pve_vnc_bridge.py ${VMID} " 2>/dev/null
  sleep 1
  rm -f "$PWFILE" "$LOGFILE"

  "$PY" "${SCRIPT_DIR}/pve_vnc_bridge.py" "$VMID" "$NODE" "$PORT" "$PWFILE" > "$LOGFILE" 2>&1 &
  BRIDGE_PID=$!

  for i in $(seq 1 20); do
    grep -q "listening on" "$LOGFILE" 2>/dev/null && break
    sleep 0.5
  done

  PW=$(cat "$PWFILE" 2>/dev/null || echo "")
  # REAL BUG, confirmed 2026-08-22 via a live from-scratch run: vncdo
  # itself can hang indefinitely on a bad/half-open TCP connection to
  # the local bridge port -- caught live as a genuinely stuck process
  # (11+ minutes, never returned) that stalled an entire Ansible
  # playbook run across all 5 VMs. Wrap it in a hard `timeout` so a
  # single bad connection attempt can never block longer than this
  # script's own retry loop expects.
  OUT=$(timeout 20 "$VNCDO" -s "127.0.0.1::${PORT}" -p "$PW" "$CMDFILE" 2>&1)
  RC=$?
  echo "$OUT"

  kill "$BRIDGE_PID" 2>/dev/null
  wait "$BRIDGE_PID" 2>/dev/null

  if [ $RC -eq 0 ] && ! echo "$OUT" | grep -qi "Authentication failed\|Cannot connect"; then
    exit 0
  fi

  echo "vnc_click.sh cycle $cycle failed, retrying..." >&2
  sleep 1
done

echo "vnc_click.sh: all cycles failed" >&2
exit 1
