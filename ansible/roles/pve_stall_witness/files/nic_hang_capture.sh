#!/bin/bash
# nic_hang_capture.sh -- started by kernel_witness.sh at the first "Detected Hardware
# Unit Hang" of an episode. Everything is local: the network is dead by now, so
# this writes to disk and fsyncs every pass. The HA watchdog resets the node about
# 60 s after the hang begins, so the loop is sized to land ~25 passes before that.
#
# What it answers (these are the discriminators the 2026-11 hangs left open):
#   - is TDH (hardware head) frozen or advancing between passes?     ethtool -d
#   - is RX still counting, or did the whole MAC stop?               ethtool -S, ip -s
#   - are the NIC's interrupts still firing?                         /proc/interrupts
#   - did the driver's own reset path ever run?                      kernel log lines
#   - what was on the wire / what does the NIC actually send?        pcap
#
# Output: /root/nic-hang/<stamp>/  (one file per tool, one "###" section per pass)
set -u
NIC="${1:-nic0}"
OUT="/root/nic-hang/$(date +%Y%m%dT%H%M%S)"
PASSES="${PASSES:-30}"
GAP="${GAP:-2}"
mkdir -p "$OUT"
PCI=$(basename "$(readlink -f "/sys/class/net/$NIC/device" 2>/dev/null)")

snap() { # file command...
  local f="$OUT/$1.txt"; shift
  { echo "### $(date -Is) uptime=$(cut -d' ' -f1 /proc/uptime) :: $*"; timeout -k 1 5 "$@" 2>&1; } >> "$f"
}

{
  echo "capture start $(date -Is) nic=$NIC pci=$PCI kernel=$(uname -r)"
  ethtool -i "$NIC"; ethtool -k "$NIC"; ethtool -a "$NIC"; ethtool --show-priv-flags "$NIC"
  ethtool --show-eee "$NIC"; ethtool -g "$NIC"; ethtool -c "$NIC"
  [ -n "$PCI" ] && timeout 5 lspci -vvv -s "${PCI#0000:}"
} > "$OUT/00-config.txt" 2>&1

for i in $(seq 1 "$PASSES"); do
  snap regs    ethtool -d "$NIC"
  snap stats   ethtool -S "$NIC"
  snap ipstat  ip -s link show "$NIC"
  snap tc      tc -s qdisc show dev "$NIC"
  {
    echo "### $(date -Is) pass=$i"
    grep -E "$NIC|e1000e" /proc/interrupts
    echo "tx_timeout: $(cat "/sys/class/net/$NIC/queues/tx-0/tx_timeout" 2>&1)"
    echo "carrier=$(cat "/sys/class/net/$NIC/carrier" 2>&1) operstate=$(cat "/sys/class/net/$NIC/operstate" 2>&1)"
  } >> "$OUT/irq.txt"
  # a handful of frames at the start, middle and end, bounded so it cannot wedge
  case "$i" in 1|12|25) timeout -k 1 4 tcpdump -ni "$NIC" -c 150 -w "$OUT/pcap-$i.pcap" >/dev/null 2>&1 ;; esac
  dmesg -T 2>/dev/null | grep -vE 'audit: type=|apparmor=' | tail -60 > "$OUT/dmesg-tail.txt"
  sync -f "$OUT" 2>/dev/null || sync
  sleep "$GAP"
done
echo "capture end $(date -Is)" >> "$OUT/00-config.txt"
sync -f "$OUT" 2>/dev/null || sync
