#!/bin/sh
# Convert CT 101 (tailscale-gw) from privileged to unprivileged.
#
# Why: it is the only privileged LXC on the cluster AND the perimeter host
# (tailnet subnet router + SDN NAT). A privileged container is not a
# boundary, so a compromise there is pve02 root. Everything else in the
# fleet is already unprivileged.
#
# The container already carries the tun passthrough it needs
# (lxc.cgroup2.devices.allow c 10:200 rwm + /dev/net/tun bind mount), and
# the host has nf_nat/nft_chain_nat/iptable_filter loaded, so the only
# change is the UID shift that `pct restore --unprivileged 1` performs.
#
# Downtime = restore + start (~2-4 min): SDN internet egress and tailnet
# ingress are down for that window. Rollback is the backup taken here.
set -u

# 2026-10-20: this script was run once and aborted. CT 101 is HA-MANAGED
# (ha-manager status lists `ct:101`), so `pct stop` goes through the CRM,
# which live-migrated the container off pve02 mid-run and the restore then
# refused ("can't overwrite running container"). Nothing broke, but a
# same-VMID restore needs the guest out of HA first, and the archive lives on
# node-local `vzdump-nvme`, pinning the restore to the node that holds it.
if ha-manager config ct:101 2>/dev/null | grep -q 'ct:'; then
    echo "ABORT: ct:101 is HA-managed — do not convert it ad-hoc."
    echo "  ha-manager set ct:101 --state stopped   # let the CRM stop it"
    echo "  ha-manager set ct:101 --state disabled  # keep HA off it"
    echo "  then run this on the node that holds the archive"
    exit 1
fi

ARCHIVE=""
rollback() {
    echo "ROLLBACK: restoring 101 as PRIVILEGED from ${ARCHIVE:-<none>}"
    [ -n "$ARCHIVE" ] || { echo "no archive — MANUAL INTERVENTION"; exit 1; }
    pct restore 101 "$ARCHIVE" --storage nvme-data --force 2>&1 | tail -5
    pct start 101
    sleep 10
    pct status 101
    exit 1
}

echo "=== 1. fresh backup (live) ==="
OUT=$(vzdump 101 --mode snapshot --storage vzdump-nvme --compress zstd 2>&1)
echo "$OUT" | tail -4
ARCHIVE=$(echo "$OUT" | grep -oE '/[^ ]*vzdump-lxc-101-[0-9T_:.-]+\.tar\.zst' | tail -1)
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
    echo "ARCHIVE_NOT_FOUND (got '$ARCHIVE')"; exit 1
fi
echo "archive=$ARCHIVE  size=$(du -h "$ARCHIVE" | cut -f1)"

echo "=== 2. stop 101 ==="
pct stop 101 || { echo "STOP_FAILED"; exit 1; }
sleep 5
pct status 101

echo "=== 3. restore as unprivileged ==="
if ! pct restore 101 "$ARCHIVE" --storage nvme-data --unprivileged 1 --force; then
    echo "RESTORE_FAILED"; rollback
fi

echo "=== 4. config after restore ==="
grep -E '^(unprivileged|features|net[0-9]|lxc\.|rootfs)' /etc/pve/lxc/101.conf

echo "=== 5. start ==="
if ! pct start 101; then echo "START_FAILED"; rollback; fi
sleep 20
pct status 101

echo "=== 6. inside checks ==="
pct exec 101 -- sh -c 'echo "tailscaled=$(systemctl is-active tailscaled)"; echo "ip=$(hostname -I)"; iptables -t nat -S POSTROUTING | grep -c MASQUERADE | sed "s/^/masq=/"; tailscale status 2>/dev/null | head -2' || true
echo "=== 7. outside check ==="
curl -s -o /dev/null -w 'egress=%{http_code}\n' --max-time 10 https://example.com || true
echo "done"
