#!/bin/bash
# Runs as root inside the privileged host chroot (see net_health.py). Captures, in parallel, for $2 seconds:
#   1. all Ethernet multicast/broadcast on the wired NIC (who is flooding the LAN)
#   2. 5 GHz ch149/80 MHz in monitor mode on the idle AX210 (who uses the air)
# then one real DHCP DISCOVER (offer count). Always restores the managed wlp2s0.
OUT="${1:?outdir}"
DUR="${2:-45}"
mkdir -p "$OUT"
rm -f "$OUT"/mc.pcap "$OUT"/air.pcap "$OUT"/dhcp.txt "$OUT"/root.log
exec >"$OUT/root.log" 2>&1
echo "start $(date +%T) dur=$DUR"
PHY=$(ls /sys/class/ieee80211 2>/dev/null | head -1)
NIC=$(ip -o -4 route show default | awk '{print $5; exit}')
echo "phy=$PHY nic=$NIC"

timeout "$DUR" tcpdump -i "$NIC" -n -s 64 -w "$OUT/mc.pcap" 'ether multicast' >/dev/null 2>&1 &
MCPID=$!

ok=0
if [ -n "$PHY" ]; then
  ip link set wlp2s0 down 2>/dev/null
  iw dev wlp2s0 del 2>/dev/null
  ip link del mon0 2>/dev/null
  for attempt in 1 2 3; do
    iw phy "$PHY" interface add mon0 type monitor 2>&1 && break
    sleep 1
  done
  ip link set mon0 up 2>&1
  sleep 1
  for spec in "channel 149 80MHz" "channel 149 HT20"; do
    if iw dev mon0 set $spec 2>&1; then ok=1; echo "tuned: $spec"; break; fi
    sleep 1
  done
  iw dev mon0 info 2>&1 | grep -E "type|channel"
fi
if [ "$ok" = 1 ]; then
  timeout "$DUR" tcpdump -i mon0 -s 200 -w "$OUT/air.pcap" >/dev/null 2>&1
else
  echo "TUNE_FAILED"
  sleep "$DUR"
fi
wait "$MCPID" 2>/dev/null

ip link set mon0 down 2>/dev/null
iw dev mon0 del 2>/dev/null
[ -n "$PHY" ] && iw phy "$PHY" interface add wlp2s0 type managed 2>&1
ip link set wlp2s0 up 2>&1

timeout 25 nmap --script broadcast-dhcp-discover -e "$NIC" >"$OUT/dhcp.txt" 2>&1
echo "done $(date +%T)"
chown -R adam.durham:adam.durham "$OUT"
