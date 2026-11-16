#!/bin/bash
# Weekly ZFS snapshots for the lab VMs that have NO vzdump coverage.
#
# The Tanium lab VMs (200-205) and the three small clones (270-272) are real
# state the owner does not consider disposable, but their disks are 500 GB-1 TB
# of sparse zvol, so vzdump is impractical and a full zfs send does not fit in
# any node's free space. Snapshots are the protection that DOES fit: instant,
# near-zero space until blocks diverge, and they cover the realistic failure
# modes here (bad upgrade, corruption, accidental deletion).
#
# Deliberately plain `zfs snapshot`, NOT `qm snapshot`: qm writes snapshot
# entries into the VM config and takes a VM lock, and a delete that fails
# half-way (ZFS snap already gone) leaves the VM locked in `snapshot-delete`
# with a phantom snapshot section in its config -- observed on vm270 while
# building this. ZFS-level snapshots touch no config and cannot lock a guest.
#
# Rollback (manual, e.g. after a bad Tanium upgrade):
#   qm shutdown <vmid>
#   zfs clone nvme-pool/vm-200-disk-1@auto-weekly-202643 nvme-pool/restore-200
#   (or `zfs rollback` if the current dataset should be replaced outright)
set -uo pipefail

POOL="${POOL:-nvme-pool}"
KEEP="${KEEP:-4}"
# Capacity guard (2026-11-15): on the churny Tanium zvols four weeklies held ~220 GiB
# (not the ~0 B measured on day one) and pve02's pool reached 85 %. Above
# POOL_MAX_PCT the oldest weekly of a volume that still has more than one is
# destroyed; every volume keeps its newest. At most PRESSURE_MAX_PRUNES per run,
# and ZFS must finish freeing before the next check (frees are asynchronous).
# The percentage is used/(used+avail) of the pool dataset -- the figure Proxmox shows
# for the storage and the pve_pool_capacity_high alert reads (80 %) -- not zpool's
# ALLOC/SIZE, which runs 3-6 points lower because it ignores reservations. 78 acts
# before the 80 % early warning.
# DRY_RUN=1 prints what would go. Never prunes a volume below 2 weeklies.
POOL_MAX_PCT="${POOL_MAX_PCT:-78}"
PRESSURE_MAX_PRUNES="${PRESSURE_MAX_PRUNES:-3}"
DRY_RUN="${DRY_RUN:-0}"
TAG="auto-weekly-$(date +%G%V)"
LAB_VMIDS='200|201|202|203|204|205|270|271|272'

mapfile -t vols < <(zfs list -H -o name -r "$POOL" 2>/dev/null \
    | grep -E "/vm-($LAB_VMIDS)-disk-[0-9]+$")

if [ "${#vols[@]}" -eq 0 ]; then
    echo "no lab VM volumes on this node"
    exit 0
fi

for v in "${vols[@]}"; do
    if ! zfs list -H -t snapshot -o name -r "$v" 2>/dev/null | grep -q "@$TAG$"; then
        zfs snapshot "$v@$TAG" 2>/dev/null || echo "WARN snapshot failed: $v"
    fi
    # prune: keep the newest $KEEP weekly tags, destroy older ones
    zfs list -H -t snapshot -o name -r "$v" 2>/dev/null \
        | grep -E "@auto-weekly-[0-9]{6}$" | sort \
        | head -n -"$KEEP" \
        | while read -r old; do
            zfs destroy "$old" 2>/dev/null && echo "pruned $old"
        done
done

pool_pct() { zfs list -Hp -o used,avail "$POOL" 2>/dev/null | awk '{printf "%d", 100 * $1 / ($1 + $2)}'; }

pruned=0
while [ "$(pool_pct)" -gt "$POOL_MAX_PCT" ] && [ "$pruned" -lt "$PRESSURE_MAX_PRUNES" ]; do
    # Candidate = the OLDEST weekly of each volume that still has more than one.
    # Victim = the candidate that actually holds the most space (the EFI disks hold
    # ~0 B and destroying their snapshots would relieve nothing). Below 1 GiB there
    # is nothing worth pruning.
    victim=""; victim_used=0
    for v in "${vols[@]}"; do
        mapfile -t weeklies < <(zfs list -Hp -t snapshot -o name,used -r "$v" 2>/dev/null \
            | grep -E "@auto-weekly-[0-9]{6}[[:space:]]" | sort)
        # never below TWO weeklies per volume: a guard that fires because something ELSE
        # filled the pool (as a 399 GiB staging dir did on 2026-11-15) must not eat the
        # only restore points of a VM that has no vzdump coverage
        [ "${#weeklies[@]}" -gt 2 ] || continue
        cand="${weeklies[0]%%[[:space:]]*}"
        used="${weeklies[0]##*[[:space:]]}"
        if [ "$used" -gt "$victim_used" ]; then victim="$cand"; victim_used="$used"; fi
    done
    if [ -z "$victim" ] || [ "$victim_used" -lt 1073741824 ]; then
        echo "WARN pool $POOL at $(pool_pct)% (limit $POOL_MAX_PCT%) but no prunable weekly holds more than 1 GiB"
        break
    fi
    if [ "$DRY_RUN" = 1 ]; then
        echo "WOULD pressure-prune $victim ($((victim_used / 1073741824)) GiB; pool $(pool_pct)% > $POOL_MAX_PCT%)"
        break
    fi
    if zfs destroy "$victim" 2>/dev/null; then
        echo "pressure-pruned $victim (pool was $(pool_pct)% > $POOL_MAX_PCT%)"
        pruned=$((pruned + 1))
        timeout 180 zpool wait -t free "$POOL" 2>/dev/null || sleep 10
    else
        echo "WARN could not destroy $victim"
        break
    fi
done

TF=/var/lib/node_exporter/textfile_collector
if [ -d "$TF" ] && [ "$DRY_RUN" != 1 ]; then
    {
        echo "# TYPE pve_lab_snapshot_pressure_prunes gauge"
        echo "pve_lab_snapshot_pressure_prunes $pruned"
        echo "# TYPE pve_lab_snapshot_last_run_timestamp_seconds gauge"
        echo "pve_lab_snapshot_last_run_timestamp_seconds $(date +%s)"
    } > "$TF/.pve_lab_snap.tmp" && mv -f "$TF/.pve_lab_snap.tmp" "$TF/pve_lab_snapshots.prom"
fi

echo "done on $(hostname): $(zfs list -H -t snapshot -o name -r "$POOL" 2>/dev/null | grep -c "@$TAG$") snapshot(s) tagged $TAG"
