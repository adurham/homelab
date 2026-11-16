#!/bin/bash
# pve_nic_textfile.sh -- publish the NIC hang history and the mitigation state as
# node_exporter-style textfile metrics (Alloy's textfile collector ships them).
#
# Why a metric from a log: during a hang the node has no network, so nothing can be
# pushed from it live. The persistent kernel_witness.log survives the reset, so the
# first scrape after the node returns carries "a hang happened at <time>". The
# surviving nodes' view (pve_ha_state{id="node/pveNN",state="fence"}) is the
# live signal; this one names the cause.
#
# Metrics
#   pve_nic_hang_last_timestamp_seconds{nic}  epoch of the newest "Detected Hardware
#                                             Unit Hang" line in the witness log, 0 if none
#   pve_nic_hang_lines{nic}                   how many such lines the retained log holds
#   pve_nic_offload_enabled{nic,feature}      1/0 for tso, gso, gro (drift check on the
#                                             TSO/GSO-off mitigation)
#   pve_kernel_witness_active                 1 if kernel-witness.service is running
set -u
NIC="${1:-nic0}"
DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
OUT="$DIR/pve_nic.prom"
mkdir -p "$DIR"

last=0; n=0
for f in /root/kernel_witness.log.1 /root/kernel_witness.log; do
  [ -f "$f" ] || continue
  c=$(grep -ac 'Detected Hardware Unit Hang' "$f"); n=$((n + c))
  l=$(grep -a 'Detected Hardware Unit Hang' "$f" | tail -1 | sed -E 's/^\[([^]]+)\].*/\1/')
  if [ -n "$l" ]; then
    e=$(date -d "$l" +%s 2>/dev/null || echo 0)
    [ "$e" -gt "$last" ] && last=$e
  fi
done

feat() { ethtool -k "$NIC" 2>/dev/null | awk -v k="$1:" '$1==k {print ($2=="on")?1:0; found=1} END{if(!found)print 0}'; }
active=0; systemctl is-active --quiet kernel-witness.service && active=1

# Files written straight into the pool's ROOT dataset belong to no guest and no child
# dataset, so per-guest and per-dataset space checks never see them. A 399 GiB staging
# directory lived there for a week (2026-11-15). Everything legitimate is a child dataset.
POOL="${2:-nvme-pool}"
root_bytes=$(zfs get -Hp -o value usedbydataset "$POOL" 2>/dev/null || echo 0)
ptmp=$(mktemp "$DIR/.pve_pool.XXXXXX")
{
  echo '# HELP pve_zfs_root_dataset_bytes Bytes held directly in the pool root dataset (outside every child dataset).'
  echo '# TYPE pve_zfs_root_dataset_bytes gauge'
  echo "pve_zfs_root_dataset_bytes{pool=\"$POOL\"} ${root_bytes:-0}"
} > "$ptmp"
chmod 0644 "$ptmp"
mv -f "$ptmp" "$DIR/pve_pool.prom"

tmp=$(mktemp "$DIR/.pve_nic.XXXXXX")
{
  echo '# HELP pve_nic_hang_last_timestamp_seconds Newest e1000e Detected Hardware Unit Hang line in the persistent kernel witness log (0 = none).'
  echo '# TYPE pve_nic_hang_last_timestamp_seconds gauge'
  echo "pve_nic_hang_last_timestamp_seconds{nic=\"$NIC\"} $last"
  echo '# HELP pve_nic_hang_lines Hang report lines held in the retained witness log.'
  echo '# TYPE pve_nic_hang_lines gauge'
  echo "pve_nic_hang_lines{nic=\"$NIC\"} $n"
  echo '# HELP pve_nic_offload_enabled Offload feature state on the physical NIC (1=on).'
  echo '# TYPE pve_nic_offload_enabled gauge'
  echo "pve_nic_offload_enabled{nic=\"$NIC\",feature=\"tso\"} $(feat tcp-segmentation-offload)"
  echo "pve_nic_offload_enabled{nic=\"$NIC\",feature=\"gso\"} $(feat generic-segmentation-offload)"
  echo "pve_nic_offload_enabled{nic=\"$NIC\",feature=\"gro\"} $(feat generic-receive-offload)"
  echo '# HELP pve_kernel_witness_active 1 when kernel-witness.service is running.'
  echo '# TYPE pve_kernel_witness_active gauge'
  echo "pve_kernel_witness_active $active"
} > "$tmp"
chmod 0644 "$tmp"
mv -f "$tmp" "$OUT"
