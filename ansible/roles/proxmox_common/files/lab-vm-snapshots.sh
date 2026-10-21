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

echo "done on $(hostname): $(zfs list -H -t snapshot -o name -r "$POOL" 2>/dev/null | grep -c "@$TAG$") snapshot(s) tagged $TAG"
