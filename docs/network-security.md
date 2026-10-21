# Network security model

This is the explicit threat model behind which interfaces are firewalled
where in the homelab. Written down so the next person (or me, on a tired
day) doesn't relitigate it from scratch.

## Trust zones

| Zone                     | Network             | Trust level | Why                                                                        |
| :----------------------- | :------------------ | :---------- | :------------------------------------------------------------------------- |
| Internet                 | 0.0.0.0/0           | hostile     | Untrusted by default                                                       |
| LAN                      | `192.168.86.0/24`   | trusted     | My house, my devices                                                       |
| Tailscale tailnet        | `100.64.0.0/10`     | trusted     | Authenticated via Tailscale identity; only my account's devices            |
| Private SDN              | `172.16.0.0/24`     | trusted     | VXLAN-isolated; only reachable from LAN via the Tailscale subnet router    |
| PVE Sync VLAN            | `172.20.0.0/24`     | trusted     | 802.1Q VLAN 20, corosync + ZFS replication; no gateway, physically confined to switch ports 3/4/5 |
| PVE Migrate VLAN         | `172.21.0.0/24`     | trusted     | 802.1Q VLAN 21, live-migration traffic + node-to-node SSH; same ports 3/4/5 |
| Tanium client subnet     | `172.16.0.61–73`    | semi-trust  | Test endpoints; ephemeral; treated as compromised by default               |

The private SDN is "trusted" because the perimeter (Tailscale-gw, lb-01,
dns-01) is the security boundary. CTs on the SDN can talk to each other
freely — east-west filtering between them is **not** in the threat model.

## Where firewalling lives

### Perimeter (this is the security boundary)

| Surface                 | Where                                       | Notes                                                   |
| :---------------------- | :------------------------------------------ | :------------------------------------------------------ |
| Public DNS              | de-SEC + no-ip DDNS                         | Only `*.chi.lab.amd-e.com` records exposed              |
| Tailscale subnet router | `tailscale-gw` (CT 101)                     | The only ingress to `172.16.0.0/24` from off-LAN        |
| Public HTTPS            | `lb-01` (CT 103) nginx                      | TLS termination + Authentik forward-auth + ACL by `geo` |
| Outbound proxy          | `proxy-01` (CT 108) squid                   | Used by TanOS appliances for binary downloads; listens `:3129` (ssl-bump) + `:3130` (Tanium-only lockdown) |

### Per-CT firewalls (`/etc/pve/firewall/<vmid>.fw`)

| CT  | Service        | Inbound rules                                                   |
| :-- | :------------- | :-------------------------------------------------------------- |
| 100 | authentik      | SSH/ICMP from SDN+Tailscale; :80/443/9000/9443 from lb-01 only |
| 104 | mail-01        | SSH/ICMP from SDN+Tailscale; :25 from graf-01 + authentik only |
| 108 | proxy-01 squid | SSH/ICMP + :3129/3130 from SDN+Tailscale |
| 200 | ts-01          | SSH + Tanium-specific ports from SDN+Tailscale                  |
| 201 | ts-02          | (same as 200)                                                   |
| 202-205 | tms / tzs  | (same as 200)                                                   |

Default INPUT policy is DROP (per pve-firewall), so the lists are
positive allow-lists. Unlisted ports are filtered.

The non-firewalled service CTs (101 tailscale-gw, 102 dns-01, 103
lb-01, 105 ntp-01, 106 vm-01, 107 graf-01) sit in the "trusted SDN"
zone — see next section.

### CTs intentionally NOT per-CT-firewalled

CTs 101, 102, 103, 105, 106, 107 (tailscale-gw, dns-01, lb-01, ntp-01,
vm-01, graf-01) **do not** have per-CT firewall files. Reasoning:
- They're reachable only via the perimeter (lb-01 for HTTP, Tailscale
  for SSH).
- East-west filtering between trusted CTs adds operational drag (every
  new flow needs a rule) without changing the post-compromise blast
  radius — if any one CT is compromised, the attacker can pivot via
  legitimate flows (DNS lookups, SMTP relay, OIDC redirects, etc.).
- vm-01's web UI was the lone exception — it had no auth at all.
  Now gated by Authentik forward-auth on the `victoriametrics.chi.lab.amd-e.com`
  FQDN at lb-01 (see `roles/loadbalancer_service/templates/nginx.conf.j2`).
  The direct private-IP path (`172.16.0.42:8428`) is still open within
  the SDN — Grafana datasource and Alloy push use it. (The "9 service
  CTs" above are the core 100-108 set. Separately, the personal/media
  service CTs — 113 hermes-gw-01, 114 bwt-dhcp, 115 gallery-01, 116/117
  media-ingest, 118 adblock-proxy-01, 170 frigate-01 — are likewise
  outside the per-CT-firewall model, each for its own documented reason.)
- The pve hosts are hardened against inbound from the SDN via
  `roles/pve_private_ip/`'s `PRIVATE-MONITORING-IN` chain — the
  hypervisor management plane is *not* on the SDN trust boundary.

If a single trusted CT goes compromised, the assumption is that the SDN
is fully reachable from there. Defense relies on:
- Authentik MFA gating console access
- Vault-encrypted credentials (no plaintext on disk for
  cross-service auth)
- HA replication for blast-radius recovery (compromised CT can be
  rebuilt from inventory)
- Loki-shipped audit logs catch lateral movement after the fact

### Pve hosts (the hypervisor itself)

`roles/pve_private_ip/` adds an L3 endpoint on `private` for monitoring
push, then drops all new inbound on that interface via a plain-iptables
chain (`PRIVATE-MONITORING-IN`). pve management (SSH:22, web UI:8006,
corosync) stays exclusively on `vmbr0` (LAN). Cluster firewall is
enabled at the cluster level (`/etc/pve/firewall/cluster.fw`), host
firewalls are off (enabling them broke cross-host VXLAN bridge
forwarding — see commit `0ee2eae`).

`roles/proxmox_common/` purges two services that were sitting on pve
hosts as unneeded attack surface:
- `squid` (was running standalone on pve02, leftover from an earlier
  experiment, listening on `0.0.0.0:3128` with zero usage logs)
- `rpcbind` (NFS portmap on `:111`; we don't run NFS)

Tightening pve host firewall further is a deferred plan — see
`#5 plan` in tonight's audit conversation.

### Home Assistant API tokens — OIDC account, one token per consumer (2026-10-21)

HA long-lived tokens are minted against the **`Adam Durham` user (the
Authentik/OIDC account), never the local `root` user** — owner's rule. Each
consumer gets its own named token so it can be revoked alone in
Settings → Security:

| Token name | Used by | Stored in |
| :--- | :--- | :--- |
| `victoriametrics-scrape` | VM scrape of `/api/prometheus` | vault var `homeassistant_token` |
| `hermes-gateway` | hermes gateway `.env` + both log shippers on adblock-proxy-01 | vault var `vault_hermes_gw_hass_token` |
| `hermes-agent` | the owner's MacBook `~/.hermes/.env` | local `.env` only |

Creation path: HA only mints long-lived tokens over its WebSocket API for the
authenticated user, and the OIDC login needs a browser. `auth/long_lived_access_token`
can be reached without a browser by authenticating with a 30-minute access token
for that same user — an HS256 JWT whose `iss` is one of the user's refresh-token
ids and whose key is that entry's `jwt_key` in `/config/.storage/auth`. HA then
creates and stores the long-lived entry itself; nothing is hand-edited in
`.storage`.

**IP banning stays enabled, with no exemption for the SDN.** It is real
brute-force protection — but note the failure mode: a stale token makes every
failed request count, HA bans the source, and once banned EVERY request from
that address gets `403: Forbidden` regardless of token validity. Because the
private subnet egresses through `tailscale-gw` (`192.168.86.16`), one banned
address takes the whole SDN out of Home Assistant. On 2026-10-21 three
consumers still held tokens whose refresh entry was deleted in the 10-18
rotation (`iss 9e28d1a2…`), which is what produced the 10-18 ban of `.16` and
the 10-20 ban of the owner's wired MacBook (`.45`). Both bans were cleared
(backup `ip_bans.yaml.bak-*`) and all three consumers moved to the tokens above.

### Root SSH on the PVE nodes — break-glass only (2026-10-21)

Root SSH to pve01/02/03 is deliberately available and deliberately narrow:
`/etc/ssh/sshd_config.d/00-no-root.conf` sets `PermitRootLogin no` globally and
restores `prohibit-password` only for a `Match Address` list — the three node
LAN IPs, the sync/migrate VLANs (ZFS replication and live migration need root
key SSH, so `no` without that list silently breaks every replication job), and
the owner's MacBook (192.168.86.45 wired / .53 wifi, both DHCP — re-render via
`ansible/harden_network_stack.yml` if the leases drift).

The normal path is **not** root: log in as `amd` with `ssh -A` and use plain
`sudo cmd </dev/null` (the forwarded hardware key satisfies
`pam_ssh_agent_auth`). Root SSH is for recovery when that path is unavailable.

Gotcha found the hard way: pve03 ships `/root/.ssh/authorized_keys` as a
symlink to the cluster-wide `/etc/pve/priv/authorized_keys`, but pve01/pve02
have it as a regular file holding only the three inter-node keys — so the same
laptop key works on one node and is refused on the other two. Both now carry
the break-glass keys (the YubiKey sk key and the 1Password-gated MacBook RSA);
`harden_network_stack.yml` installs them idempotently.

## When this would change

The model would tighten (add per-CT firewalls to the 9 service CTs) if
any of these become true:
- A CT starts handling untrusted user content directly (e.g., letting
  outsiders upload files)
- The homelab gets opened up to non-trusted users (family members
  with their own devices on the SDN) — note the untracked personal
  service CTs (113/115/116/117/118/170) would need per-CT firewalls too
- Tailscale ACLs are ever weakened (currently restricted to my own
  account's devices)
- A regression in lb-01 starts forwarding non-Authentik-authed traffic
  to backends

## Related

- `docs/ipam.md` — IP allocation per zone
- `docs/promtail-to-alloy-plan.md` — telemetry pipeline trust
- `roles/pve_private_ip/` — pve-host hardening
- `roles/loadbalancer_service/templates/nginx.conf.j2` — perimeter ACLs
