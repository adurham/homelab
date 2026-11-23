#!/bin/bash
# Runs as root inside the privileged host chroot (see net_health.py).
# Wi-Fi ONLY (owner's rule 2026-11-23): the wired multicast census and the DHCP DISCOVER now run
# on the Home Assistant box (/config/scripts/net_wired.py). What is left here is the 5 GHz
# ch149/80 MHz monitor capture on the idle AX210; the managed wlp2s0 is always put back.
OUT="${1:?outdir}"
DUR="${2:-45}"
mkdir -p "$OUT"
rm -f "$OUT"/air.pcap "$OUT"/root.log
exec >"$OUT/root.log" 2>&1
echo "start $(date +%T) dur=$DUR"
PHY=$(ls /sys/class/ieee80211 2>/dev/null | head -1)
echo "phy=$PHY"

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

ip link set mon0 down 2>/dev/null
iw dev mon0 del 2>/dev/null
[ -n "$PHY" ] && iw phy "$PHY" interface add wlp2s0 type managed 2>&1
ip link set wlp2s0 up 2>&1

echo "done $(date +%T)"
chown -R adam.durham:adam.durham "$OUT"
