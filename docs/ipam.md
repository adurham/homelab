# IPAM — IP and VMID allocation

Single source of truth for IP allocations and Proxmox VMIDs. Keep this in
sync when adding/removing/moving CTs or VMs.

## Networks

| Network         | CIDR              | Bridge  | Purpose                                    |
| :-------------- | :---------------- | :------ | :----------------------------------------- |
| LAN             | `192.168.86.0/24` | `vmbr0` | Home LAN — DHCP from the Nest router       |
| Private (VXLAN) | `172.16.0.0/24`   | `private` | SDN private subnet for service traffic   |

- `172.16.0.1` is the SDN gateway (proxmox VNet); CTs on `private` use it as their default route only when they need outbound to non-LAN destinations.
- `172.16.0.101` is `tailscale-gw` — subnet router advertising `172.16.0.0/24` over Tailscale.
- MTU on `private` is 1450 (1500 minus VXLAN overhead — `net_private_mtu` in `ansible/group_vars/all/vars.yml`).

## Proxmox nodes (LAN, static)

| Host    | LAN IP          | Notes                           |
| :------ | :-------------- | :------------------------------ |
| `pve01` | `192.168.86.11` | Proxmox cluster member          |
| `pve02` | `192.168.86.12` | Proxmox cluster member          |
| `pve03` | `192.168.86.13` | Proxmox cluster member          |

Source: `ansible/inventory/proxmox.yml`.

## Service CTs (private subnet)

| Hostname        | VMID | Private IP       | LAN IP (if any)    | Role                                        |
| :-------------- | :--- | :--------------- | :----------------- | :------------------------------------------ |
| `authentik`     | 100  | `172.16.0.20`    | -                  | SSO / OIDC provider                         |
| `tailscale-gw`  | 101  | `172.16.0.101`   | `192.168.86.32`    | Subnet router; ingress gateway              |
| `dns-01`        | 102  | `172.16.0.10`    | -                  | Bind9 authority for `chi.lab.amd-e.com`     |
| `lb-01`         | 103  | `172.16.0.30`    | DHCP (`192.168.86.x`) | Nginx L7 reverse proxy                  |
| `mail-01`       | 104  | `172.16.0.40`    | -                  | Postfix → iCloud SMTP relay                 |
| `ntp-01`        | 105  | `172.16.0.11`    | -                  | Chrony, syncs against `time.nist.gov`       |
| `vm-01`         | 106  | `172.16.0.42`    | DHCP (`192.168.86.x`) | VictoriaMetrics + blackbox + Loki + Promtail |
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

## Tanium clients (test endpoints)

VMIDs 300-313, IPs `172.16.0.60–73`. See `inventory/proxmox.yml` under `tanium_clients`.

## VMID conventions

- **100–199** — core service CTs
- **200–299** — Tanium server/module/zone CTs
- **300–399** — Tanium client test endpoints
- **400+** — reserved / unused

## Where IPs are defined (in order of authority)

This is fragmented and should be consolidated. Today there are three sources:

1. **`ansible/inventory/proxmox.yml`** — every host's `ansible_host:` and (for monitoring CTs) `net_private_ip:`. **This is the de-facto authority** since ansible uses `ansible_host` for connections.
2. **`ansible/group_vars/all/vars.yml`** — partial coverage as `ip_*` vars: `ip_dns_primary`, `ip_authentik`, `ip_loadbalancer`, `ip_mail_server`, `ip_ntp_server`, `ip_tailscale_gw`. Missing: `ip_proxy`, `ip_grafana`, `ip_vm`. Roles consume these variables in their `pct create` invocations.
3. **`ansible/deploy_proxy.yml`** — defines `ip_proxy: "172.16.0.12"` as a play-level var because it's not in `vars.yml`.

When the `ip_*` var doesn't match the inventory's `ansible_host` (as happened with vm-01/mail-01), bad things happen silently. Goal: every service should have its IP defined in `vars.yml` once, with the inventory's `ansible_host` derived from it.

## Adding a new CT

1. Pick a free IP in the appropriate range (check this file).
2. Pick a free VMID (next sequential within the convention range).
3. Add the host to `ansible/inventory/proxmox.yml` with `ansible_host`, `vmid`, and `target_node`.
4. If the CT belongs to the private subnet, add it to the `private_subnet` parent group in `proxmox.yml` so it inherits the work-MacBook ProxyCommand.
5. Add an `ip_<name>` entry to `ansible/group_vars/all/vars.yml` (don't define it inline in the playbook).
6. Update this file with the new allocation.

## Open inconsistencies

- `vars.yml` is incomplete — missing `ip_proxy`, `ip_grafana`, `ip_vm`. Roles for those CTs hardcode the IP via inventory or per-playbook vars. **Fix:** consolidate.
- The Tanium IPs aren't in `vars.yml` at all (they're set on each host in inventory). Acceptable since they're not referenced by other roles.
