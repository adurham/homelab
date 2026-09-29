#!/bin/bash
# lab_witness.sh — 1s-resolution reachability witness for the recurring
# simultaneous-unclean-reboot investigation on pve01/02/03.
#
# WHY: five events since 2026-09-16 where all three nodes hard-reset within
# seconds of each other (wtmp "crash", fsck at boot) with house power up.
# Two candidate mechanisms survive:
#   (a) a power event on the lab branch/strip killing all three at once
#   (b) HA self-fencing reboots after a >60s loss of inter-node connectivity
#       ("fencing armed (CRM watchdog active)") — also unclean, also
#       simultaneous, also with house power unaffected.
# This witness records the per-second sequence so the NEXT event discriminates:
# the exact second each peer and each switch stops answering, plus this node's
# own NIC and quorum state right up to the instant it dies.
#
# Probes are TCP, not ICMP: the PVE host firewall drops inter-node ICMP by
# design (trusted-IPSET rules allow only corosync UDP 5405 + SSH TCP 22), so
# a ping-based witness would read a permanent false "down" for every peer.
#
# Log is transition-only (+30s heartbeat) and fsync'd, so the tail survives an
# abrupt power loss. Rotates at 5 MB. Deployed by Hermes 2026-09-29.
# Unit file: lab-witness.service
LOG=/root/lab_witness.log
MAXB=5242880

# name ip port   ("icmp" = ICMP echo; nodes use TCP/22 because inter-node ICMP
# is firewalled off by design)
TARGETS="pve01 192.168.86.11 22
pve02 192.168.86.12 22
pve03 192.168.86.13 22
netgear 192.168.86.51 80
sg105e 192.168.86.15 80
gw 192.168.86.1 icmp"

declare -A PREV

log() {
  printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"
  sync -f "$LOG" 2>/dev/null || sync
}

probe() { # ip port
  if [ "$2" = icmp ]; then
    ping -c1 -W1 -n "$1" >/dev/null 2>&1
  else
    timeout 1 bash -c "exec 3<>/dev/tcp/$1/$2" >/dev/null 2>&1
  fi
}

rotate() {
  local sz
  sz=$(wc -c <"$LOG" 2>/dev/null || echo 0)
  if [ "$sz" -gt "$MAXB" ]; then
    mv -f "$LOG" "$LOG.1"
    log "rotated (previous log moved to $LOG.1)"
  fi
}

log "witness started on $(hostname) boot_id=$(cat /proc/sys/kernel/random/boot_id) uptime_s=$(cut -d' ' -f1 /proc/uptime)"
hb=0
while true; do
  while read -r n ip port; do
    [ -n "$n" ] || continue
    if probe "$ip" "$port"; then s=up; else s=down; fi
    if [ "${PREV[$n]:-unknown}" != "$s" ]; then
      log "STATE $n=$s was=${PREV[$n]:-unknown}"
      PREV[$n]=$s
    fi
  done <<<"$TARGETS"

  hb=$((hb + 1))
  if [ $((hb % 30)) -eq 0 ]; then
    nic=$(cat /sys/class/net/nic0/operstate 2>/dev/null || echo '?')
    q=$(pvecm status 2>/dev/null | awk -F': *' '/^Quorate/{print $2; exit}')
    log "HB nic0=$nic quorate=${q:-?} uptime_s=$(cut -d' ' -f1 /proc/uptime)"
  fi
  rotate
  sleep 1
done
