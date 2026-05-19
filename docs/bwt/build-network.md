# BWT Lab — Phase 1: Network infrastructure

Build the isolated 10.99.0.0/24 SDN subnet, gateway, and DHCP server.

## Why a dedicated SDN VNet (not just an existing bridge)

The repro needs a clean subnet with predictable subnet boundaries because
the test depends on `site_throttle_subnets` matching client IPs exactly.
Carving from the existing `private` (172.16.0.0/24) subnet would mix
test traffic with real services, contaminate `iptables` byte counters
on pve01's `private` bridge, and require firewall surgery to keep BWT
traffic isolated.

Using a fresh VXLAN VNet under the existing `homelab` zone:
- Reuses the same VXLAN underlay (no new corosync config)
- Spans all pve nodes automatically (VXLAN handles L2 across the cluster)
- Isolated subnet means clean filtering and zero collision

## Why VXLAN (not Simple) zone for BWT

Considered switching BWT to a Simple zone since Simple zones support
Proxmox 9.1's built-in DHCP plugin. Rejected because:

- Simple zones are single-node (bridge exists only on the node where the
  VM lives) — BWT VMs would all have to live on pve01
- For multi-node BWT VMs, we'd need VXLAN regardless
- We can run our own dnsmasq in a CT instead — clean, no pve-host
  package install, lab-isolated

**Hard constraint discovered:** PVE 9.1's SDN DHCP plugin is restricted
to Simple zones. The `--dhcp dnsmasq` option on `pvesh create
/cluster/sdn/zones` is rejected for VXLAN zones with `unexpected
property 'dhcp'`. The subnet-level `--dhcp-range` and `--dhcp-dns-server`
options ARE accepted but no daemon is spawned — they're cosmetic on
VXLAN zones in this PVE version. Source-verified at
`/usr/share/perl5/PVE/Network/SDN/Zones/SimplePlugin.pm` (only Simple
plugin imports `PVE::Network::SDN::Dhcp`).

## Why a dedicated DHCP CT (not pve-host dnsmasq)

Tried installing dnsmasq directly on pve nodes — Adam pushed back hard:
"we should NOT be installing random packages on the proxmox hosts."
Correct call. The fix: run dnsmasq inside a dedicated LXC CT
(`bwt-dhcp`, vmid 114) on the bwt bridge. pve hosts stay clean; the
DHCP server can be torn down or rebuilt without touching pve.

## Network address layout

```
10.99.0.1          pve01 BWT bridge IP (gateway + SNAT to internet via vmbr0)
10.99.0.2          bwt-dhcp CT (static)
10.99.0.10         bwt-ts (static — set during TanOS post-clone reconfig)
10.99.0.11-14      bwt-zs-01..04 (static)
10.99.0.50-250     DHCP dynamic pool (BWT LXC clients land here)
```

The .10-.14 range is intentionally outside the DHCP pool to avoid
conflicts between static TanOS appliances and dynamic client IPs.

## DNS strategy: public resolvers

BWT VMs cannot reach the homelab's `dns-01` at 172.16.0.10 — pve01's
`PRIVATE-MONITORING-IN` iptables chain drops new connections from
non-trusted sources at the `private` bridge. Empirically confirmed:
ping from 10.99.0.x to 172.16.0.10 = 100% loss.

Rather than punch holes in the existing lockdown firewall (which exists
for good reason), BWT just uses public DNS — `1.1.1.1` and `8.8.8.8`
pushed via dnsmasq DHCP options. BWT subnet has internet access via
pve01's SNAT, so public resolvers work fine. BWT-internal hostnames
(`bwt-ts.bwt.local` etc.) don't resolve, but they're never needed —
ansible uses inventory IPs directly.

## Files this phase produces

| File | Purpose |
|------|---------|
| `ansible/group_vars/all/vars.yml` (+ `net_bwt_*` vars) | Network constants — single source of truth |
| `ansible/inventory/proxmox.yml` (+ `bwt_lab` group) | Inventory for all BWT VMs/CTs |
| `ansible/inventory/group_vars/bwt_servers.yml` | TanOS SSH overrides (tanadmin user, ProxyJump pve01) |
| `ansible/inventory/group_vars/bwt_clients.yml` | LXC client SSH overrides (root, ProxyJump pve01) |
| `ansible/inventory/group_vars/bwt_services.yml` | bwt-dhcp CT SSH overrides |
| `ansible/roles/proxmox_sdn/` (extended) | Creates `bwt` VNet + subnet |
| `ansible/roles/pve_bwt_gateway/` (new) | pve01 holds 10.99.0.1 + SNAT (persistent) |
| `ansible/roles/bwt_dhcp_host/` (new) | Provisions bwt-dhcp CT + dnsmasq config |
| `ansible/setup_sdn.yml` (existing, used) | Applies SDN config |
| `ansible/setup_bwt_gateway.yml` (new) | Applies gateway role to pve01 |
| `ansible/deploy_bwt_dhcp.yml` (new) | Provisions bwt-dhcp CT (phase 1 = pct create on pve01, phase 2 = install dnsmasq inside the CT) |

## Verification

```
# After setup_sdn.yml
ansible proxmox_nodes -m shell -a 'ip -br addr show bwt'
# Should show 'bwt UP fe80::...' on all 3 nodes (no IPv4 yet)

# After setup_bwt_gateway.yml
ansible pve01 -m shell -a 'ip -br addr show bwt; iptables -t nat -L POSTROUTING -n -v | grep 10.99'
# Should show 10.99.0.1/24 on bwt; MASQUERADE rule for 10.99.0.0/24 -> vmbr0

# After deploy_bwt_dhcp.yml — full DHCP smoke test
ssh root@192.168.86.11 'pct create 999 \
  /var/lib/vz/template/cache/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname bwt-dhcp-test --cores 1 --memory 128 \
  --net0 name=eth0,bridge=bwt,ip=dhcp \
  --storage nvme-data --rootfs nvme-data:2 \
  --unprivileged 1 --start 1'
ssh root@192.168.86.11 'pct exec 999 -- ip -br addr show eth0; pct exec 999 -- ping -c1 1.1.1.1'
# Should show 10.99.0.xxx assigned + ping to 1.1.1.1 (via SNAT) working
# Cleanup: pct stop 999; pct destroy 999 --purge
```

## Pitfalls

- **Don't install random packages on pve hosts.** Tried `apt install
  dnsmasq` on pve nodes during exploration. Wrong. Roll back with `apt
  remove --purge dnsmasq dnsmasq-base dns-root-data` and run DHCP in a
  dedicated CT instead.
- **Subnet-level DHCP options without zone-level support do nothing on
  VXLAN zones.** `pvesh set /cluster/sdn/vnets/<vnet>/subnets/<id>
  -dhcp-range start-address=...,end-address=...` succeeds, but no
  daemon spawns. Empirically: `ss -tulnp | grep :67` returns nothing.
  Don't waste time chasing this — go straight to a dedicated DHCP CT.
- **Existing homelab firewall blocks bwt → private.** pve01's
  `PRIVATE-MONITORING-IN` chain has `DROP` for non-RELATED/ESTABLISHED
  traffic from any source. BWT subnet doesn't break this — it's
  intentional isolation. Use public DNS instead of dns-01.
- **Templates aren't auto-replicated across pve nodes.** When provisioning
  CTs across multiple nodes, the LXC template must exist on each target.
  pveam cache is per-host. Workaround: `rsync` template from pve01 to
  the others, or use `ansible_play_batch` to coordinate downloads.
