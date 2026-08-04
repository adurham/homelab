# IPAM — IP and VMID allocation

Single source of truth for IP allocations and Proxmox VMIDs. Keep this in
sync when adding/removing/moving CTs or VMs.

## Networks

| Network         | CIDR              | Bridge  | Purpose                                    |
| :-------------- | :---------------- | :------ | :----------------------------------------- |
| LAN             | `192.168.86.0/24` | `vmbr0` | Home LAN — DHCP from the Nest router       |
| Private (VXLAN) | `172.16.0.0/24`   | `private` | SDN private subnet for service traffic   |
| BWT Lab (VXLAN) | `10.99.0.0/24`    | `bwt`     | Isolated subnet for Tanium bandwidth-throttle repro (NEC 00271560 et al) |
| PVE Sync (VLAN 20) | `172.20.0.0/24` | `vmbr0.20` | Isolated L2 segment for corosync + ZFS replication, physically confined to switch ports 3/4/5 — see below |

## Physical switch chain (LAN, non-Proxmox)

Physical topology upstream of pve01/02/03 and the exo cluster Mac Studios:

```
AT&T BGW (IP Passthrough)
  -> Google Nest Wifi Pro (main unit)
       -> NETGEAR GS108Ev4 (GS108E-400NAS, 8-port managed) — see below
            -> TP-Link 8-port switch (unmanaged)
                 -> TP-Link 5-port switch (unmanaged)
```

| Device | Model | LAN IP | Notes |
| :--- | :--- | :--- | :--- |
| `netgear-switch-01` | GS108Ev4 (GS108E-400NAS) | `192.168.86.62` (DHCP reservation) | 8-port "Easy Smart" managed switch. No SSH/SNMP/API — CGI web-form config only (login password: see label / vault). Managed via `ansible/roles/netgear_gs108ev4/` + `ansible/manage_netgear_switch.yml`. MAC `28:94:01:77:1d:80`. |

**Status (2026-08-04):** switch reachable at `192.168.86.62` via a DHCP
reservation (added directly in AdGuard, not yet mirrored into the Ansible
role). Port mapping confirmed via live link-toggle tests (bring interface
down/up on each host, watch for the corresponding port's traffic counters
on `/portStatistics.cgi` to freeze — NOT via UP/DOWN status labels, which
are unreliable on macOS since `ifconfig down` only sets an administrative
flag and doesn't reliably drop the physical PHY link; Linux's
`ip link set down` / `networksetup -setnetworkserviceenabled ... off` do
drop the real link and are trustworthy for this test):

| Port | Device | Confirmed via |
| :--- | :--- | :--- |
| 3 | `pve03` (192.168.86.13) | `ip link set nic0 down`, kernel dmesg `NIC Link is Down`, 2x clean repeat |
| 4 | `pve02` (192.168.86.12) | same method, 1x clean |
| 5 | `pve01` (192.168.86.11) | same method, 2x clean (1st attempt had a false negative from too-coarse SSH polling — use ≥1.5s poll interval and a ≥10s down window) |
| 7 | `macstudio-m4-2` (192.168.86.202) | confirmed by physically unplugging the cable — port showed "AVAILABLE" (down) and .202 stopped responding to ping |
| 8 | `macstudio-m4-1` (192.168.86.201) | same, physical unplug — port "AVAILABLE" and .201 stopped responding |
| 1, 2, 6 | unknown (likely uplink + 1-2 spares) | — |

**IMPORTANT CORRECTION:** an earlier version of this doc (same day) claimed
both Mac Studios were confirmed NOT on this switch, based on
`networksetup -setnetworkserviceenabled Ethernet off/on` toggle tests
showing zero effect on any port counter. That conclusion was **wrong** —
a physical cable-unplug test immediately afterward showed both Mac Studios
ARE on this switch (ports 7 and 8). Lesson: `networksetup ... off` is
**not reliable enough for this test either** — like `ifconfig down`, it
does not reliably drop the physical PHY link on these Mac Studios (Apple
Silicon / Thunderbolt-adjacent NIC hardware may power-manage the PHY
differently than the e1000e-based Proxmox NICs, where the same class of
test DID correlate correctly via kernel dmesg `NIC Link is Down`). For
Mac hardware, only a genuine physical unplug is trustworthy for this kind
of port-mapping test — do not trust `ifconfig down` or `networksetup off`
as a proxy for "physical link down" on macOS, on any NIC.

QoS mode note: the switch's QoS page defaults to **802.1P/DSCP** mode,
which reads priority from tags already inside packets — useless here since
Proxmox/replication traffic isn't tagged that way. **Port-based** mode is
the correct choice for prioritizing ports 3/4/5 directly regardless of
packet contents; switching QoS Mode to Port-based should expose a Priority
tab. As of 2026-08-04 this hasn't been applied — see "Root cause found and
fixed" below; QoS is now considered a secondary belt-and-suspenders step,
not the primary fix. Login password was changed by the user and stored in
1Password (no longer the factory default) — I no longer have programmatic
access to this switch.

### Root cause found and fixed (2026-08-04): synchronized replication bursts

The original throughput-dip investigation (2026-08-03) suspected shared-
uplink contention between Proxmox sync traffic and other LAN traffic.
Confirmed via VictoriaMetrics `node_network_transmit_bytes_total{device=
"vmbr0"}` query_range across pve01/02/03: multiple daily events where
**all 3 nodes simultaneously spike to a combined 100+ MB/s (800+ Mbps)**
on their LAN-facing interface for 4-5 minutes at a stretch (e.g. observed
20-46 MB/s per node, all 3 nodes, at the same timestamps).

Root cause: `/etc/pve/replication.cfg` had 20 replication jobs on a
`schedule *:N/15` pattern (offsets 0-14) — but 20 jobs into only 15 minute
slots meant 5 collisions where two jobs fire in the same minute, each
already rate-limited to 15 MB/s but stacking when combined. This is a
pmxcfs-managed live cluster file, NOT Ansible-templated — no repo drift
risk, but also nothing to update in `ansible/` for this fix.

**Fix applied:** rewrote the schedule to `*:N/20` with N assigned 0-19
sequentially per job (one job per unique minute in a 20-minute cycle
instead of a 15-minute one) — zero collisions, verified
`sort(schedules) == [0..19]` before applying. Backup saved on pve03 at
`/etc/pve/replication.cfg.bak-<timestamp>`. Applied by writing the new
config directly (no `pvesr` CLI edit-by-edit needed since it's one file);
`pvescheduler.service` re-reads `replication.cfg` from pmxcfs each cycle,
no restart required.

**Verified:** post-fix, max single-node vmbr0 throughput over a 15-minute
window was ~15 MB/s (down from a confirmed 50 MB/s pre-fix peak), with
zero timestamps where 2+ nodes simultaneously exceeded 20 MB/s (versus
multiple confirmed multi-node collision windows pre-fix). Root cause
resolved without touching the switch at all.

- `172.16.0.1` is `tailscale-gw` — both the SDN VNet gateway and the Tailscale subnet router advertising `172.16.0.0/24` over Tailscale. CTs on `private` use it as their default route only when they need outbound to non-LAN destinations.
- `10.99.0.3` is `tailscale-gw` eth2 on the `bwt` bridge — same CT (101) carries the BWT-lab subnet router, advertising `10.99.0.0/24` over Tailscale.
- MTU on `private` and `bwt` is 1450 (1500 minus VXLAN overhead — `net_private_mtu` / `net_bwt_mtu` in `ansible/group_vars/all/vars.yml`).

## PVE Sync network (VLAN 20, 172.20.0.0/24) — isolated corosync + replication

Built 2026-08-04 alongside the replication-schedule root-cause fix, as a
belt-and-suspenders layer: corosync/replication traffic is now on its own
L2 segment, physically confined to switch ports 3/4/5, invisible to every
other device on the LAN (no gateway, not routed, Google Home/Nest Wifi
Pro never sees it exist). Same physical wire as the LAN (each pve node has
only one NIC) so this does NOT add bandwidth capacity — the replication-
schedule fix already solved the bandwidth-contention problem; this adds
isolation on top.

**Switch side:** Advanced 802.1Q VLAN mode, VLAN 20 "pve-sync" created,
ports 3/4/5 set Tagged (T) for VLAN 20 while staying Untagged/PVID=1 for
the default LAN VLAN (confirmed via PVID Table: ports 3/4/5 show `1*, 20`,
all other ports show `1*` only). Every other port is Excluded (E) from
VLAN 20 entirely.

**Proxmox side (`/etc/network/interfaces` on each node):**
```
auto vmbr0
iface vmbr0 inet static
	address 192.168.86.1X/24
	gateway 192.168.86.1
	bridge-ports nic0
	bridge-stp off
	bridge-fd 0
	bridge-vlan-aware yes
	bridge-vids 20          # REQUIRED -- without this, vmbr0.20 exists but nic0
	                        # never egresses tagged VLAN 20 frames; symptom is
	                        # `bridge vlan show dev nic0` listing only vlan 1,
	                        # ping/ssh across the VLAN just times out silently.

auto vmbr0.20
iface vmbr0.20 inet static
	address 172.20.0.1X/24   # .11=pve01, .12=pve02, .13=pve03, no gateway
```

**Firewall (`/etc/pve/firewall/cluster.fw`):** Proxmox's cluster firewall
is enabled with default-deny-style rules gated on trusted IPSETs — adding
the VLAN alone isn't enough, traffic gets silently dropped unless
explicitly allowed. Added:
```
[IPSET pve_sync_vlan]
172.20.0.11
172.20.0.12
172.20.0.13

IN ACCEPT -source +pve_sync_vlan -p udp -dport 5405 -log nolog # corosync
IN ACCEPT -source +pve_sync_vlan -p tcp -dport 22 -log nolog   # ZFS replication (SSH transport)
```
Scoped narrowly (just corosync + SSH, not a broad subnet-wide ACCEPT) per
user preference, since isolation is the whole point of this network.

**Replication traffic redirect (`/etc/pve/datacenter.cfg`):**
```
replication: secure,network=172.20.0.0/24
```
This is the actual Proxmox-native mechanism (`man pvesr`, NETWORK section)
for repointing replication traffic onto a dedicated network — no per-job
config needed, applies cluster-wide immediately.

**Corosync:** NOT yet added as a second ring (`link1`) on this network —
still single-ring on the LAN (`link0`). This is the one remaining piece
**Corosync: added as a second ring, DONE and verified (2026-08-04).**
`link1` added on the isolated VLAN with `knet_link_priority` set so it's
preferred over the LAN (`link0`) — corosync actively uses the isolated
link, LAN stays configured as automatic failover only.

`/etc/pve/corosync.conf` changes (config_version bumped 3→4):
```
nodelist {
  node {
    name: pve01
    ...
    ring0_addr: 192.168.86.11
    ring1_addr: 172.20.0.11     # added
  }
  ... (same pattern for pve02/pve03)
}

totem {
  ...
  interface {
    linknumber: 0
    knet_link_priority: 5      # LAN — lower priority, failover only
  }
  interface {
    linknumber: 1
    knet_link_priority: 10     # VLAN 20 — higher priority, preferred
  }
  ...
}
```

**Apply mechanism note (corrected from an earlier wrong assumption):**
the documented Proxmox pattern is NOT "write to `corosync.conf.new` and
pmxcfs auto-swaps it" — that file sitting on disk does nothing on its own.
The actual mechanism (per `man pvecm`) is: copy to `.new`, edit `.new`,
then explicitly `mv corosync.conf.new corosync.conf` yourself. That `mv`
is what pmxcfs picks up and hot-applies to the running corosync cluster-
wide, no restart needed. Backup the working config first regardless
(`cp corosync.conf corosync.conf.bak`).

**Verified priority actually works (not just configured):** raw packet
counts from a short tcpdump window were NOT a reliable signal (passive-
mode keepalives on the non-primary link created noise). The real proof:
`corosync-cmapctl -m stats` per-link byte counters, diffed over a ~60s
window post-change — `link0.tx_data_bytes` delta was exactly 0 (fully
idle) while `link1.tx_data_bytes` grew by ~2.75MB in the same window.
`corosync-cfgtool -s` / `-n` on all 3 nodes confirmed both links enabled
+ connected to every peer. `pvecm status` confirmed `Quorate: Yes, Nodes: 3`
before, during, and after the corosync.conf swap — zero disruption.

## Proxmox nodes (dual-homed)

pve hosts are on the LAN by default; `roles/pve_private_ip/` adds a static
IP on the `private` SDN bridge so they have a private-subnet source IP for
Alloy push to vm-01:8428. Inbound on `private` is dropped via the
`PRIVATE-MONITORING-IN` iptables user chain — pve management stays
LAN-only despite the L3 endpoint on the SDN.

| Host    | LAN IP          | Private IP    | Notes                           |
| :------ | :-------------- | :------------ | :------------------------------ |
| `pve01` | `192.168.86.11` | `172.16.0.2`  | Proxmox cluster member          |
| `pve02` | `192.168.86.12` | `172.16.0.3`  | Proxmox cluster member          |
| `pve03` | `192.168.86.13` | `172.16.0.4`  | Proxmox cluster member          |

Source: `ansible/inventory/proxmox.yml` + `roles/pve_private_ip/defaults/main.yml`.

## Service CTs (private subnet)

| Hostname        | VMID | Private IP       | LAN IP (if any)    | Role                                        |
| :-------------- | :--- | :--------------- | :----------------- | :------------------------------------------ |
| `authentik`     | 100  | `172.16.0.20`    | -                  | SSO / OIDC provider                         |
| `tailscale-gw`  | 101  | `172.16.0.1`     | `192.168.86.32`    | SDN VNet gateway + Tailscale subnet router  |
| `dns-01`        | 102  | `172.16.0.10`    | -                  | Bind9 authority for `chi.lab.amd-e.com`     |
| `lb-01`         | 103  | `172.16.0.30`    | DHCP (`192.168.86.x`) | Nginx L7 reverse proxy                  |
| `mail-01`       | 104  | `172.16.0.40`    | -                  | Postfix → iCloud SMTP relay                 |
| `ntp-01`        | 105  | `172.16.0.11`    | -                  | Chrony, syncs against `time.nist.gov`       |
| `vm-01`         | 106  | `172.16.0.42`    | DHCP (`192.168.86.x`) | VictoriaMetrics + blackbox + Loki + Alloy   |
| `graf-01`       | 107  | `172.16.0.41`    | -                  | Grafana + image renderer                    |
| `proxy-01`      | 108  | `172.16.0.12`    | -                  | Squid caching proxy                         |
| `adblock-proxy-01` | 118 | `172.16.0.49`  | -                  | mitmproxy explicit HTTPS proxy for personal-device Discord ad-stripping (Tailscale-only ingress, joins tailnet directly like hermes-gw-01) |

`172.16.0.40` was previously assigned to **both** `mail-01` and `vm-01` (ARP race). Resolved 2026-05-01 — moved `vm-01` to `.42`. See commit `12bb4c2`.

## Tanium cluster

| Hostname  | VMID | Private IP       | Role                  |
| :-------- | :--- | :--------------- | :-------------------- |
| `ts-01`   | 200  | `172.16.0.51`    | Tanium Server         |
| `ts-02`   | 201  | `172.16.0.52`    | Tanium Server         |
| `tms-01`  | 202  | `172.16.0.53`    | Tanium Module Server  |
| `tms-02`  | 203  | `172.16.0.54`    | Tanium Module Server  |
| `tzs-01`  | 204  | `172.16.0.55`    | Tanium Zone Server    |
| `tzs-02`  | 205  | `172.16.0.56`    | Tanium Zone Server    |

## BWT lab (bandwidth-throttle repro)

Separate from the existing `tanium_cluster` — uses TanOS appliance VMs on the
isolated `bwt` SDN VNet (`10.99.0.0/24`, VLAN 200). 1× TS + 4× ZS for the
server side; LXC clients for the load drivers. See
`inventory/proxmox.yml` under `bwt_lab` and the `tanium-bandwidth-throttle`
skill for context. Pre-staged Tanium RPMs land in `files/tanium-<version>/`
(gitignored) via `scripts/tanium/fetch_artifactory_bundle.sh`.

Network isolation: the `bwt` subnet is intentionally walled off from the
`private` subnet (172.16.0.0/24) by pve01's `PRIVATE-MONITORING-IN` firewall.
BWT hosts can reach the internet via SNAT through pve01 (10.99.0.1) but
cannot reach `dns-01`, `vm-01`, etc. — BWT uses Cloudflare/Google DNS pushed
by `bwt-dhcp`. Ansible reaches BWT VMs via ProxyJump through pve01.

| Hostname     | VMID | BWT IP                  | Role                              |
| :----------- | :--- | :---------------------- | :-------------------------------- |
| `bwt-dhcp`   | 114  | `10.99.0.2` (static)    | dnsmasq DHCP server (Debian LXC)  |
| `bwt-ts`     | 220  | `10.99.0.10` (static)   | Tanium Server (TanOS)             |
| `bwt-zs-01`  | 221  | `10.99.0.11` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-02`  | 222  | `10.99.0.12` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-03`  | 223  | `10.99.0.13` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-04`  | 224  | `10.99.0.14` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-tc-01`  | 320  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-02`  | 321  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-03`  | 322  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-04`  | 323  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-05`  | 324  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-06`  | 325  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-07`  | 326  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-08`  | 327  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |

DHCP pool: 10.99.0.50–250 (12h lease). 10.99.0.1 is the gateway (pve01),
10.99.0.2 is `bwt-dhcp` (this server), 10.99.0.10–14 are reserved for the
five TanOS servers (excluded from DHCP because TanOS sets static IP at
install time via kickstart).

## Tanium clients (test endpoints)

VMIDs 300-313, IPs `172.16.0.60–73`. See `inventory/proxmox.yml` under `tanium_clients`.

## VMID conventions

- **100–113** — core service CTs (authentik, dns-01, ntp-01, etc.)
- **115–118** — personal/media service CTs (gallery-01, media-ingest-01/02, adblock-proxy-01)
- **114** — BWT lab service CTs (`bwt-dhcp`)
- **200–219** — existing `tanium_cluster` placeholders (ts-01/02, tms-01/02, tzs-01/02)
- **220–249** — BWT lab TanOS VMs (`bwt-ts`, `bwt-zs-01..04`)
- **250–253** — Windows test VMs (win-sql-01, win-ts-01, win-tms-01, win-tzs-01)
- **300–319** — existing `tanium_clients` LXC endpoints
- **320–339** — BWT lab LXC clients (`bwt-tc-01..NN`)
- **400+** — reserved / ad-hoc test VMs (e.g. 400 = Some-Other-ECF-Testing)
- **9000-9999** — Proxmox templates (9000=Windows Server 2022, 9001=TanOS 1.8.6 fresh-install, 9002=TanOS 1.8.6 BWT-ready)

## Where IPs are defined (in order of authority)

1. **`ansible/group_vars/all/vars.yml`** — `ip_*` vars are the canonical
   source for the 9 core service CTs:
   `ip_dns_primary`, `ip_ntp_server`, `ip_proxy`, `ip_authentik`,
   `ip_loadbalancer`, `ip_mail_server`, `ip_grafana`, `ip_vm`,
   `ip_tailscale_gw`. Plus `ip_homeassistant` (the off-cluster HA host
   on the LAN that hosts AdGuard for DoT upstream + iOS push). Same
   file also defines `net_private_*` (SDN: range/gw/bridge/mtu) and
   `net_lan_*` (range, gateway).
2. **`ansible/inventory/proxmox.yml`** — every host's `ansible_host:`.
   For the 9 core CTs, this is templated as `"{{ ip_<name> }}"`, so
   `vars.yml` and inventory can't drift. Tanium hosts (cluster +
   clients) and the pve LAN IPs are inlined here directly because
   nothing else needs to consume them as vars.
3. **`ansible/roles/pve_private_ip/defaults/main.yml`** — pve hosts'
   private-subnet IPs (`pve_private_ip_map`).

When the `ip_*` var doesn't match the inventory's `ansible_host` (as
happened with vm-01/mail-01 before the consolidation), bad things
happen silently. The current pattern keeps them in lockstep.

## Adding a new CT

1. Pick a free IP in the appropriate range (check this file).
2. Pick a free VMID (next sequential within the convention range).
3. Add an `ip_<name>` entry to `ansible/group_vars/all/vars.yml`.
4. Add the host to `ansible/inventory/proxmox.yml` with
   `ansible_host: "{{ ip_<name> }}"`, plus `vmid` and `target_node`.
5. If the CT belongs to the private subnet, ensure it's a member of the
   `private_subnet` parent group in `proxmox.yml` (directly or via a
   child group) so it inherits the work-MacBook ProxyCommand.
6. Update this file with the new allocation.
