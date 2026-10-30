#!/bin/bash
# nic_stall_watch.sh -- catch "link up but nothing passes" at the instant it happens.
#
# WHY (2026-10-30): pve01 and pve02 lose their own network path for a few seconds
# several times a day (their 1 s witness shows EVERY probe dying at once while
# survivors see only that node drop), the HA lock is lost, and the softdog resets
# the node ~110 s later. Carrier stays up and nothing is logged in the shipped
# window (journald is volatile by design, Alloy's buffer dies with the reset), so
# the cause - NIC driver hang vs switch port vs cable vs upstream - was unknown.
#
# WHAT THIS DOES: probes the gateway over TCP every 2 s. On 3 consecutive failures
# it dumps, ONCE per stall, what the NIC itself sees:
#   * carrier/operstate/speed       - link up or down at the MAC level
#   * 1 s counter deltas            - rx_packets STILL CLIMBING during the stall means
#                                     the NIC is still receiving (switch broadcasts/ARP
#                                     keep arriving) -> fault is upstream of the NIC;
#                                     rx frozen with carrier=1 -> the NIC's RX path died
#   * ethtool -S error counters     - driver-level errors
#   * dmesg NIC lines               - the kernel ring buffer is live RAM, so this
#                                     shows what the driver said AT stall time even
#                                     though the journal never reaches disk
#   * neigh/failed probe detail
# Output is appended to /root/nic_stall.log and fsync'd per event, so it survives
# the self-fence reset that follows ~2 min later.
#
# Unit: nic-stall-watch.service  (Restart=always). Quiet unless a stall happens.
set -u
IF=nic0
GW=192.168.86.1
LOG=/root/nic_stall.log
MAXB=1048576
fails=0
consec=0

log_event() {
  {
    echo "=== $(date -Is) STALL detected: gateway $GW unreachable (carrier check follows)"
    echo "carrier=$(cat /sys/class/net/$IF/carrier 2>/dev/null) operstate=$(cat /sys/class/net/$IF/operstate 2>/dev/null) speed=$(cat /sys/class/net/$IF/speed 2>/dev/null)"
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
  sync -f "$LOG" 2>/dev/null
}

if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAXB" ]; then
  mv "$LOG" "$LOG.1"
fi
echo "nic_stall_watch started pid=$$ at $(date -Is), iface=$IF gw=$GW" >> "$LOG"

while :; do
  if timeout 2 bash -c "</dev/tcp/$GW/80" 2>/dev/null; then
    fails=0
  else
    fails=$((fails + 1))
    if [ "$fails" -ge 3 ]; then
      if [ "$consec" -eq 0 ]; then
        log_event
        consec=1
      fi
    fi
  fi
  [ "$fails" -eq 0 ] && consec=0
  sleep 2
done
