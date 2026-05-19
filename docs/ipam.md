# IPAM — IP and VMID allocation

Single source of truth for IP allocations and Proxmox VMIDs. Keep this in
sync when adding/removing/moving CTs or VMs.

## Networks

| Network         | CIDR              | Bridge  | Purpose                                    |
| :-------------- | :---------------- | :------ | :----------------------------------------- |
| LAN             | `192.168.86.0/24` | `vmbr0` | Home LAN — DHCP from the Nest router       |
| Private (VXLAN) | `172.16.0.0/24`   | `private` | SDN private subnet for service traffic   |
| BWT Lab (VXLAN) | `10.99.0.0/24`    | `bwt`     | Isolated subnet for Tanium bandwidth-throttle repro (NEC 00271560 et al) |

- `172.16.0.1` is `tailscale-gw` — both the SDN VNet gateway and the Tailscale subnet router advertising `172.16.0.0/24` over Tailscale. CTs on `private` use it as their default route only when they need outbound to non-LAN destinations.
- `10.99.0.3` is `tailscale-gw` eth2 on the `bwt` bridge — same CT (101) carries the BWT-lab subnet router, advertising `10.99.0.0/24` over Tailscale.
- MTU on `private` and `bwt` is 1450 (1500 minus VXLAN overhead — `net_private_mtu` / `net_bwt_mtu` in `ansible/group_vars/all/vars.yml`).

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
