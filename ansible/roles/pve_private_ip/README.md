# roles/pve_private_ip

Gives each pve host a static IPv4 on the `private` SDN bridge so it can
push monitoring telemetry (Alloy → vm-01:8428) without traversing the
LAN gateway. Hardens inbound on that interface so the pve management
plane stays LAN-only despite having an L3 endpoint on the SDN.

## What it does

1. Removes the apt-packaged `prometheus-node-exporter` (silently
   replaced by Alloy on these hosts; was port-conflicting with the old
   `roles/common_monitoring/` install — see the "Surprise on pve hosts"
   note in `docs/promtail-to-alloy-plan.md`).
2. Renders `/etc/network/interfaces.d/private-monitoring` with
   `iface private inet static / address {{ pve_private_ip }}/24`.
   Reloads via `ifreload -a`.
3. Drops a small systemd oneshot + `/usr/local/sbin/pve-private-firewall`
   helper that adds an iptables `INPUT` rule via a dedicated
   `PRIVATE-MONITORING-IN` chain — drops new inbound, accepts
   ESTABLISHED/RELATED. Lives in a user chain so pve-firewall reloads
   don't wipe it.

## Key variables (`defaults/main.yml`)

- `pve_private_ip_map` — `{pve01: 172.16.0.2, pve02: .3, pve03: .4}`.
- `pve_private_ip` — derived from the map by `inventory_hostname`.

## Why not pve-firewall host.fw?

Tried first — enabling host firewall (`enable: 1` in
`/etc/pve/nodes/<node>/host.fw`) broke cross-host VXLAN bridge
forwarding for CTs (vm-01 became unreachable from CTs on other pve
nodes). The plain-iptables-in-user-chain approach doesn't trigger that
interaction. See commit `0ee2eae` for the full debug.

## Where it's invoked

`deploy_monitoring.yml`'s "Configure pve hosts for monitoring egress"
play, which runs before "Install Telemetry Agents" so Alloy has a
working push path when it deploys.
