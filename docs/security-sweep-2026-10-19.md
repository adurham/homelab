# Lab security sweep — 2026-10-19

Scope: every host in the ansible inventory plus the three Macs, Home Assistant,
and the public edge. Read-only audit; no configuration was changed except the
`hermes` sudoers grant called out at the end.

Method: one shell audit (`/tmp/lab_audit.sh`, effective `sshd -T` where root,
shadow/sudoers/SUID where root), run through ansible as the inventory's own
user (root or `amd`+become); macOS checks over SSH; HA via the SSH add-on;
edge via nginx config, public DNS and a hairpin probe of the WAN address.

Coverage: 35 hosts audited, 3 Macs, HA, edge. 17 hosts unreachable (see bottom).

## Internet-facing surface

Public IPv4 108.88.208.88 (No-IP) forwards only 80/443 to `lb-01`; 22 and 8006
are closed from the WAN. Only `auth.` and `tanium.` resolve in public DNS.

Every 443 server block except the Authentik login and Tanium carries an explicit
ACL at the top of the block:

```
# ACL: Block external access
if ($is_internal = 0) { return 403; }
```

`$is_internal` (geo map) = LAN 192.168.86.0/24, SDN 172.16.0.0/24, Tailscale
100.64.0.0/10, localhost. So the public surface is exactly two names:

| Host name | Gate | External check |
| :-- | :-- | :-- |
| auth | Authentik login; `auth_login` rate limit 10 r/min per real IP | public by design |
| tanium | console reachable; credential endpoints `/auth` and `/api/v2/session` return 403 unless internal | verified 403 from check-host nodes in DE and JP |
| proxmox, homeassistant, grafana, hermes, whoami, victoriametrics, gallery, hermes-api | `$is_internal` ACL → 403 from the WAN; app-level auth behind it | config verified in live `nginx -T` |

TLS: Let's Encrypt wildcard `*.chi.lab.amd-e.com`, valid to 2027-01-16.
HSTS present; TLS 1.2/1.3 only.

### Correction (same day)

An earlier draft of this document called the Proxmox and Home Assistant blocks
internet-facing P1s. That was wrong: both carry the `$is_internal` ACL, so they
403 from the WAN. The mistake came from two bad checks — a substring scan of
`nginx -T` that looked for `allow`/`auth_request`/`limit_req` and never for the
`if ($is_internal = 0)` form, and grepping `configuration.yaml` for HA's
`ip_ban_enabled` when HA's `http:` config lives in `.storage/http` (it is set:
`ip_ban_enabled: true`, `login_attempts_threshold: 5`,
`trusted_proxies: 192.168.86.34/32`, i.e. lb-01's LAN leg). Corrected here.

### Residual (internal / tailnet scope, not public)

- PVE `root@pam` has no TFA entry and a usable password. Reachable from LAN,
  SDN and the tailnet only.
- HA: 6 users; the two real ones (`root` [owner], `Adam Durham`) have no MFA
  credentials. Login is IP-banned after 5 failures, internal-only at the edge.
- Authentik does have MFA: `akadmin` has a TOTP device, `adam.durham` a
  WebAuthn device.

## Host findings

| Finding | Hosts | Notes |
| :-- | :-- | :-- |
| `PasswordAuthentication yes` | adblock-proxy-01, authentik, dns-01, frigate-01, graf-01, hermes-gw-01, lb-01, mail-01, ntp-01, proxy-01, tailscale-gw, vm-01 | Not exploitable today: the only non-root human account (`amd`) is locked (`!`), and root login is `no` (gated) or `prohibit-password`. Still one password-set away from a hole. |
| Pending updates | 35–104 per host | Highest: tc-oracle8 104, media-ingest-02 94, tc-ubuntu24 87, pve01/02/03 77, hermes-gw-01 64. |
| No host firewall | 12 containers (`ufw` inactive), studios' macOS firewall off | Matches the documented "trusted SDN" model; the PVE per-CT firewall covers 9 CTs and pve-firewall is enabled/running. Flagged, not treated as a defect. |
| Unknown authorized key | tailscale-gw `amd`: `ssh-ed25519 … hft-bot-direct-no-1password` | Persistent login that is neither the token nor 1Password. Confirm it is still needed. |
| Key hygiene | 7 containers + 3 PVE nodes: `amd` holds the three inter-node `root@pveNN` keys and a duplicated `ssh-rsa … Macbook` | Left over from the root-era key copy; remove for least privilege. |
| No fail2ban/sshguard | everywhere | SSH brute force is only bounded by the perimeter. |
| macOS | MacBook: FileVault/SIP/Gatekeeper on, firewall on, stealth off, Remote Login on, password auth default (`yes`) | Studios: FileVault/SIP on, **firewall disabled**, Remote Login on, password auth `yes`. LAN-only. |
| Tailnet | 14 nodes, all owner devices plus `tatis-iphone` (`suzumi.ashiya`, offline 52d) and an unnamed `mlhvyy0pwxmn` | `tailscale-gw` advertises `172.16.0.0/24`; confirm the second user's device is still intended and ACL-scoped. |
| HA plain HTTP | `192.168.86.2:8123` on the LAN | TLS only at the LB. |
| MacBook AirPlay | `*:5000`, `*:7000` | Standard macOS receiver; LAN-only. |

### What is solid

- Token-gated sudo on all 16 fleet hosts: root SSH refused, `amd`+sudo silent,
  key file holds one sk key only, fails closed without an agent (verified in the
  same session, see the completion audit).
- Authentik forward-auth on the internal-service names; login rate limited.
- Tanium's pre-auth credential POST is blocked from the internet by geo.
- Grafana returns 401 anonymously; no anonymous dashboards.
- No world-writable directories under /etc, /usr/local, /opt.
- SUID binaries: only the distro set on each host. The "unusual" hits are all
  container image layers under `/var/lib/containerd` (plus HAOS's own
  `s6-overlay-suexec`); nothing outside an image snapshot. Note that
  frigate-01 and authentik still carry stale `containerd.corrupt-2026…` /
  `containerd.bak-2026…` snapshot trees — inert, but worth deleting for disk.
- Only `root` has a usable password hash among the accounts checked; `amd` is
  locked everywhere.

## Unreachable (17)

bwt-dhcp, bwt-ts, bwt-zs-01…04, bwt-tc-01…08, tc-debian11, tms-01, tzs-01,
tzs-02. The BWT lab segment looks powered down; the rest are inventory rot.
`pve02` and `homeassistant.local` failed the first ping pass and answered on the
audit pass.

## Changes made in this session

- `hermes-service-restart` on hermes-gw-01: replaced the `systemctl restart
  hermes-*` wildcard with explicit unit names (gateway, gateway-dashboard,
  serve, dashboard, bare and `.service`). Verified: `reset-failed
  hermes-serve` rc=0 as the `hermes` user, `restart ssh` and `restart
  hermes-attacker` both refused.
