#!/bin/bash
# netgear_mgmt_probe.sh -- 15 s reachability record for the GS108Ev4 management
# interface (192.168.86.51) and its ARP presence.
#
# WHY: the switch's control plane has been unreachable for >=17 h while its data
# plane keeps forwarding (no ARP reply, no http on 80/443, no NSDP answer, and it
# emits nothing on the wire). A power cycle is the only way to tell "wedged CPU"
# from "dead unit" and to get the port table back, so this records:
#   * exactly when the management interface goes away (the power cycle) and
#     whether it comes back, and how long it takes
#   * whether it dies AGAIN later without a power cycle (a repeat would confirm a
#     failing unit rather than a one-off state)
# Output is fsync'd per line so it survives a self-fence reset of this node.
#
# Unit: netgear-mgmt-probe.service (Restart=always).
set -u
TARGET=192.168.86.51
LOG=/root/netgear_mgmt.log
MAXB=1048576
prev=""
while :; do
  if timeout 3 bash -c "exec 3<>/dev/tcp/$TARGET/80" 2>/dev/null; then state=http-ok
  elif ping -c 1 -W 1 "$TARGET" >/dev/null 2>&1;           then state=icmp-only
  else state=no-answer
  fi
  if [ "$state" != "$prev" ]; then
    printf '%s %s (was %s) uptime=%s\n' "$(date -Is)" "$state" "${prev:-unknown}" "$(cut -d' ' -f1 /proc/uptime)" >> "$LOG"
    sync -f "$LOG" 2>/dev/null || sync
    prev="$state"
  fi
  if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAXB" ]; then mv -f "$LOG" "$LOG.1"; fi
  sleep 15
done
