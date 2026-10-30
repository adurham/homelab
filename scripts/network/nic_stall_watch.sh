#!/bin/bash
# nic_stall_watch.sh -- catch "link up but nothing passes" at the instant it happens,
# and record whether the MACHINE was still executing while its network was dead.
#
# WHY (2026-10-30): pve01 and pve02 lose their own network path for a few seconds
# several times a day (their 1 s witness shows EVERY probe dying at once while
# survivors see only that node drop), the HA lock is lost, and the softdog resets
# the node ~110 s later. Carrier stays up, nothing reaches disk (volatile journald,
# Alloy's buffer dies with the reset). Two things were unproven: WHERE the datapath
# stops, and whether the machine itself was still running during the 110 s gap.
#
# NOTE on the other witness: lab_witness.sh's HB line is written every 30 loop
# iterations, and a fully-failed round takes ~7 s (7 probes x 1 s timeout), so it
# CANNOT emit an HB inside a 110 s outage. Its silence during a stall is a cadence
# property, not evidence of a hang. This script supplies the missing resolution.
#
# WHAT IT DOES
#   every 2 s : append a machine-local progress line to $PROG (no network involved)
#   every 5th : fsync $PROG (so <=10 s of trace can be lost to a hard reset)
#   3 fails   : dump what the NIC sees (carrier, 1 s counter deltas, ethtool -S,
#               dmesg NIC lines from the live ring buffer, peer probes) to $LOG,
#               fsync both, then spend 180 s writing an fsync'd progress line every
#               second -- pinning the exact second the machine stopped executing
#               against the second its network died.
#
# Discriminators this produces at the next stall
#   rx_packets still climbing  -> frames still arriving from the switch; the fault
#                                 is in this node's RX/stack, not the cable/port
#   rx frozen, carrier 1       -> nothing arrives at the NIC at all
#   progress stops at T        -> the machine wedged at T (kernel/hardware hang)
#   progress runs to T+110     -> the machine stayed alive and was fenced by the
#                                 softdog after losing the cluster lock
#
# Unit: nic-stall-watch.service (Restart=always). Quiet unless a stall happens.
set -u
IF=nic0
GW=192.168.86.1
LOG=/root/nic_stall.log
PROG=/root/progress_witness.log
MAXB=2097152
fails=0
consec=0
iter=0

sync_file() { sync -f "$1" 2>/dev/null || sync; }

rotate_if_big() {
  local f=$1
  if [ -f "$f" ] && [ "$(stat -c%s "$f" 2>/dev/null || echo 0)" -gt "$MAXB" ]; then
    mv -f "$f" "$f.1"
  fi
}

progress() {   # $1 = extra marker (optional)
  printf '%s uptime=%s%s\n' "$(date -Is)" "$(cut -d' ' -f1 /proc/uptime)" "${1:-}" >> "$PROG"
}

log_event() {
  {
    echo "=== $(date -Is) STALL detected: gateway $GW unreachable (carrier check follows)"
    echo "carrier=$(cat /sys/class/net/$IF/carrier 2>/dev/null) operstate=$(cat /sys/class/net/$IF/operstate 2>/dev/null) speed=$(cat /sys/class/net/$IF/speed 2>/dev/null) uptime_s=$(cut -d' ' -f1 /proc/uptime)"
    echo "-- 1s counter deltas (frozen vs climbing is the discriminator)"
    for f in rx_packets tx_packets rx_bytes tx_bytes rx_dropped tx_dropped rx_errors tx_errors rx_missed_errors; do
      v1=$(cat /sys/class/net/$IF/statistics/$f 2>/dev/null || echo -1)
      sleep 1
      v2=$(cat /sys/class/net/$IF/statistics/$f 2>/dev/null || echo -1)
      echo "   $f: $v1 -> $v2 (delta $((v2 - v1)))"
    done
    echo "-- ethtool -S (errors/drops)"
    ethtool -S "$IF" 2>/dev/null | grep -iE "error|drop|miss|reset|fifo|jabber|hang" | head -14
    echo "-- dmesg NIC lines (driver's own words; ring buffer, not the journal)"
    dmesg 2>/dev/null | grep -iE "e1000e|$IF|Link is|NIC" | tail -25
    echo "-- probe detail"
    echo "   gw-icmp: $(ping -c 1 -W 1 $GW >/dev/null 2>&1 && echo up || echo down)"
    for p in 192.168.86.11 192.168.86.12 192.168.86.13; do
      [ "$p" = "$(hostname -I | awk '{print $1}')" ] && continue
      echo "   $p:22: $(timeout 2 bash -c "</dev/tcp/$p/22" 2>/dev/null && echo up || echo down)"
    done
    echo "=== end stall record"
  } >> "$LOG"
  sync_file "$LOG"
}

for f in "$LOG" "$PROG"; do rotate_if_big "$f"; done
echo "nic_stall_watch started pid=$$ at $(date -Is), iface=$IF gw=$GW" >> "$LOG"
progress " (watcher start)"

while :; do
  iter=$((iter + 1))
  progress
  [ $((iter % 5)) -eq 0 ] && sync_file "$PROG"

  if timeout 2 bash -c "</dev/tcp/$GW/80" 2>/dev/null; then
    fails=0
  else
    fails=$((fails + 1))
    if [ "$fails" -ge 3 ] && [ "$consec" -eq 0 ]; then
      log_event
      progress " (stall: network dead)"
      # 180 s of fsync'd 1 Hz local progress: pins the machine's last executing
      # second against the network death and the softdog reset that follows.
      for _ in $(seq 180); do
        sleep 1
        progress " (post-stall)"
        sync_file "$PROG"
        rotate_if_big "$PROG"
      done
      consec=1
      fails=0
    fi
  fi
  [ "$fails" -eq 0 ] && consec=0
  sleep 2
done
