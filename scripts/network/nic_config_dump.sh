#!/bin/bash
# nic_config_dump.sh -- dump every NIC setting that could differ between a node
# that stalls and one that does not (self-fence investigation, 2026-10-30).
set -u
IF=nic0
echo "=== $(hostname) $(uname -r)"
echo "-- driver: $(ethtool -i $IF | tr '\n' ' ')"
echo "-- link: speed=$(cat /sys/class/net/$IF/speed) duplex=$(cat /sys/class/net/$IF/duplex) mtu=$(cat /sys/class/net/$IF/mtu) carrier=$(cat /sys/class/net/$IF/carrier)"
echo "-- offloads:"
ethtool -k $IF 2>/dev/null | grep -E "^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|large-receive-offload|rx-vlan-offload|tx-vlan-offload|scatter-gather|rx-checksumming|tx-checksumming|rx-gro-list|tx-gso-list):" | sed 's/^/     /'
echo "-- coalesce: $(ethtool -c $IF 2>/dev/null | tr '\n' ' ')"
echo "-- ring: $(ethtool -g $IF 2>/dev/null | tr '\n' ' ')"
echo "-- channels: $(ethtool -l $IF 2>/dev/null | tr '\n' ' ')"
echo "-- pause: $(ethtool -a $IF 2>/dev/null | tr '\n' ' ')"
echo "-- eee: $(ethtool --show-eee $IF 2>/dev/null | tr '\n' ' ')"
echo "-- thou: $(ethtool -s $IF 2>/dev/null | tr '\n' ' ')"
echo "-- pci: $(lspci -vv -s 00:1f.6 2>/dev/null | grep -E "LnkCap:|LnkCtl:|ASPM|LTR" | tr -s ' ' | tr '\n' ' ')"
echo "-- interrupts:"; grep -i e1000e /proc/interrupts 2>/dev/null | sed 's/^/     /'
echo "-- rx-usecs-irq: $(cat /sys/class/net/$IF/device/irq 2>/dev/null)"
echo "-- ethtool stats (wedge-relevant):"
ethtool -S $IF 2>/dev/null | grep -iE "tx_timeout|tx_restart|tx_hang|rx_over|rx_missed|rx_length|rx_crc|rx_errors|tx_errors|rx_dropped|tx_dropped|rx_no_buffer|align_errors|rx_long" | sed 's/^/     /'
echo "-- dmesg e1000e (this boot):"; dmesg 2>/dev/null | grep -i e1000e | tail -8 | sed 's/^/     /'
echo
