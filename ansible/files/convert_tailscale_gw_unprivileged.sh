#!/bin/sh
# CT 101 tailscale-gw: privileged -> unprivileged, HA-aware.
#
# Third iteration. What the earlier attempts taught us:
#   * CT 101 is HA-managed with crs ha-rebalance-on-start=1, so `pct stop`
#     becomes a CRM relocation. Drive it with `ha-manager set --state ...`.
#   * `pct restore --unprivileged 1` aborts because the archive contains
#     /var/spool/postfix/dev/{random,urandom} char devices, and the restore
#     helper runs tar inside a user namespace where mknod is not permitted.
#     Postfix recreates those nodes on every start (mtimes prove it), so we
#     drop them in the live CT before taking the backup.
#   * PVE 9.2.21 has no --ignore-unpack-errors for pct restore.
#
# Outage: SDN egress + tailnet ingress, ~2-3 min.
set -u
VZID=101
ARCHIVE=""
FAILED=0

rollback() {
    echo "!!! ROLLBACK: restoring $VZID as PRIVILEGED"
    ha-manager set "ct:$VZID" --state stopped >/dev/null 2>&1
    sleep 5
    pct restore "$VZID" "$ARCHIVE" --storage nvme-data --force >/dev/null 2>&1 \
        || { echo "ROLLBACK RESTORE FAILED — MANUAL"; exit 1; }
    ha-manager set "ct:$VZID" --state started
    sleep 15
    echo "rollback status: $(pct status $VZID 2>&1)"
    exit 1
}
gate() { if eval "$2"; then echo "GATE OK   $1"; else echo "GATE FAIL $1"; FAILED=1; fi; }

echo "=== 1. drop postfix chroot dev nodes in the live CT, then back up ==="
pct exec $VZID -- sh -c 'rm -f /var/spool/postfix/dev/random /var/spool/postfix/dev/urandom; ls /var/spool/postfix/dev/ | tr "\n" " "'
echo
OUT=$(vzdump $VZID --mode snapshot --storage vzdump-nvme --compress zstd 2>&1)
echo "$OUT" | grep -E 'INFO: Finished|INFO: Backup job'
ARCHIVE=$(echo "$OUT" | grep -oE '/[^ ]*vzdump-lxc-'"$VZID"'-[0-9T_:.-]+\.tar\.zst' | tail -1)
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || { echo "NO_ARCHIVE"; exit 1; }
echo "archive=$ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

echo "=== 2. HA stop, wait for 'stopped' ==="
ha-manager set "ct:$VZID" --state stopped
i=0; st=""
while [ $i -lt 30 ]; do
    st=$(ha-manager status 2>/dev/null | sed -n "s/^service ct:$VZID ([^)]*, \(.*\))$/\1/p")
    [ "$st" = "stopped" ] && break
    sleep 5; i=$((i+1))
done
echo "ha_state=$st after $((i*5))s"
[ "$st" = "stopped" ] || { echo "HA_DID_NOT_STOP"; ha-manager set "ct:$VZID" --state started; exit 1; }

echo "=== 3. restore as unprivileged ==="
if ! pct restore "$VZID" "$ARCHIVE" --storage nvme-data --unprivileged 1 --force 2>&1 | tail -6; then
    echo "RESTORE_FAILED"; rollback
fi
# pipeline masks the real status; check the config instead
grep -q '^unprivileged: 1' /etc/pve/lxc/$VZID.conf || { echo "NOT_UNPRIVILEGED"; rollback; }

echo "=== 4. config gates ==="
gate "three NICs"        "[ \$(grep -c '^net[0-9]:' /etc/pve/lxc/$VZID.conf) -eq 3 ]"
gate "tun allow kept"    "grep -q 'lxc.cgroup2.devices.allow: c 10:200 rwm' /etc/pve/lxc/$VZID.conf"
gate "tun mount kept"    "grep -q 'lxc.mount.entry: /dev/net/tun' /etc/pve/lxc/$VZID.conf"
if [ "$FAILED" = 1 ]; then echo "CONFIG_GATE_FAILED"; rollback; fi

echo "=== 5. hand back to HA, wait for 'started' ==="
ha-manager set "ct:$VZID" --state started
i=0; st=""
while [ $i -lt 30 ]; do
    st=$(ha-manager status 2>/dev/null | sed -n "s/^service ct:$VZID ([^)]*, \(.*\))$/\1/p")
    [ "$st" = "started" ] && break
    sleep 5; i=$((i+1))
done
echo "ha_state=$st after $((i*5))s"
[ "$st" = "started" ] || { echo "DID_NOT_START"; rollback; }
sleep 12

echo "=== 6. live gates ==="
gate "tailscaled active"    "pct exec $VZID -- systemctl is-active --quiet tailscaled"
gate "3 MASQUERADE rules"   "[ \$(pct exec $VZID -- iptables -t nat -S POSTROUTING 2>/dev/null | grep -c MASQUERADE) -eq 3 ]"
gate "ip_forward=1"         "[ \$(pct exec $VZID -- sysctl -n net.ipv4.ip_forward 2>/dev/null) = 1 ]"
gate "route 172.16.0.0/24"  "pct exec $VZID -- tailscale status --json 2>/dev/null | grep -q '172.16.0.0/24'"
gate "SDN egress"           "pct exec $VZID -- curl -s -o /dev/null -m 8 https://deb.debian.org"
if [ "$FAILED" = 1 ]; then echo "LIVE_GATE_FAILED"; rollback; fi

echo "=== DONE ==="
pct config $VZID | grep -E '^(unprivileged|features|net[0-9]|lxc\.)'
