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
| Outbound proxy          | `proxy-01` (CT 108) squid                   | Used by TanOS appliances for binary downloads           |

### Per-CT firewalls (`/etc/pve/firewall/<vmid>.fw`)

| CT  | Service        | Inbound rules                                                   |
| :-- | :------------- | :-------------------------------------------------------------- |
| 100 | authentik      | SSH/ICMP from SDN+Tailscale; :80/443/9000/9443 from lb-01 only |
| 104 | mail-01        | SSH/ICMP from SDN+Tailscale; :25 from graf-01 + authentik only |
| 108 | proxy-01 squid | SSH/ICMP + :3128/3129 from SDN+Tailscale                        |
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
  the SDN — Grafana datasource and Alloy push use it.
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

## When this would change

The model would tighten (add per-CT firewalls to the 9 service CTs) if
any of these become true:
- A CT starts handling untrusted user content directly (e.g., letting
  outsiders upload files)
- The homelab gets opened up to non-trusted users (family members
  with their own devices on the SDN)
- Tailscale ACLs are ever weakened (currently restricted to my own
  account's devices)
- A regression in lb-01 starts forwarding non-Authentik-authed traffic
  to backends

## Related

- `docs/ipam.md` — IP allocation per zone
- `docs/promtail-to-alloy-plan.md` — telemetry pipeline trust
- `roles/pve_private_ip/` — pve-host hardening
- `roles/loadbalancer_service/templates/nginx.conf.j2` — perimeter ACLs
