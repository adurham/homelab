#!/bin/sh
# LXC privilege boundary audit — run on a PVE node as root (sudo bash -s).
# Prints one line per guest with the settings that decide whether a container
# compromise is a host-root compromise.
for id in $(pct list 2>/dev/null | awk 'NR>1{print $1}'); do
    name=$(pct config "$id" 2>/dev/null | sed -n 's/^hostname: *//p')
    unp=$(pct config "$id" 2>/dev/null | sed -n 's/^unprivileged: *//p')
    feat=$(pct config "$id" 2>/dev/null | sed -n 's/^features: *//p')
    app=$(pct config "$id" 2>/dev/null | sed -n 's/^lxc.apparmor.profile: *//p')
    keyctl=$(pct config "$id" 2>/dev/null | sed -n 's/^lxc.cgroup2.devices.allow: *//p' | head -1)
    mp=$(pct config "$id" 2>/dev/null | grep -E '^mp[0-9]+: ' | sed -e 's/[, ].*//' | tr '\n' ' ')
    dev=$(pct config "$id" 2>/dev/null | grep -E '^dev[0-9]+: ' | sed -e 's/^\(dev[0-9]*\): \([^,]*\).*/\1=\2/' | tr '\n' ' ')
    net=$(pct config "$id" 2>/dev/null | grep -E '^net[0-9]+: ' | sed -e 's/^net[0-9]*: //' | tr '\n' ' ' | cut -c1-120)
    printf 'guest=%s name=%s unprivileged=%s features=%s apparmor=%s keyctl=%s mp=[%s] dev=[%s] net=[%s]\n' \
        "$id" "${name:-?}" "${unp:-0}" "${feat:-none}" "${app:-default}" "${keyctl:-none}" "$mp" "$dev" "$net"
done
echo "--- host kernel ---"
uname -r
echo "--- pve-firewall ---"
systemctl is-active pve-firewall 2>/dev/null
pve-firewall status 2>/dev/null | head -3
