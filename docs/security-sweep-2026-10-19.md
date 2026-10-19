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

| Finding | Hosts | Status |
| :-- | :-- | :-- |
| `PasswordAuthentication yes` | adblock-proxy-01, authentik, dns-01, frigate-01, graf-01, hermes-gw-01, lb-01, mail-01, ntp-01, proxy-01, tailscale-gw, vm-01 | **Fixed 2026-10-19** — `harden_ssh_password_auth.yml` writes `/etc/ssh/sshd_config.d/00-no-password.conf` (PasswordAuthentication/KbdInteractive/PermitEmptyPasswords no), validates with `sshd -t`, reloads, then asserts `sshd -T`. Verified on all 12: `passwordauthentication no`, and a password-only client gets `Permission denied (publickey)`. |
| Key hygiene | 7 containers + 3 PVE nodes: `amd` held the three inter-node `root@pveNN` keys and a duplicated ansible key | **Fixed 2026-10-19** — `prune_amd_authorized_keys.yml` (backup, temp file, refuses to install unless the sk key and ansible key survive). Now 2–3 keys per host: sk, ansible, and 1Password RSA where it existed. |
| Unknown authorized keys left in place | pve01/02/03 `amd`: `Tanium Macbook` (RSA-2048, fingerprint tscpVpoF…); pve01 also an uncommented ECDSA key (ZGPKFcc4…) | No matching private key on this Mac. Left in place pending an owner call — likely the work laptop. |
| Pending updates | 35–104 per host | Open. Highest: tc-oracle8 104, media-ingest-02 94, tc-ubuntu24 87, pve01/02/03 77, hermes-gw-01 64. |
| No host firewall | 12 containers (`ufw` inactive), studios' macOS firewall off | Matches the documented "trusted SDN" model; the PVE per-CT firewall covers 9 CTs and pve-firewall is enabled/running. Studio firewall left alone — a live exo session is using those boxes. |
| Unknown bot key | tailscale-gw `amd`: `hft-bot-direct-no-1password` | Intentional — the private half is `~/.ssh/hft_bot_direct` on this Mac. Owner call whether it still needs to sit on the perimeter host. |
| No fail2ban/sshguard | everywhere | Open (low). SSH brute force is bounded by the perimeter + key-only auth now. |
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
- `harden_ssh_password_auth.yml` (new): key-only SSH on the 12 hosts above.
  Applied and asserted; password-only login is refused at the protocol level.
- `prune_amd_authorized_keys.yml` (new): dropped the inter-node cluster keys and
  duplicate ansible key from `amd`'s file on 10 hosts (3 PVE + 7 containers),
  with a backup and a guard that refuses to install a file missing the token or
  ansible key. Backups: `/home/amd/.ssh/authorized_keys.bak-*`.
- Mac Studios: `/etc/ssh/sshd_config.d/00-no-password.conf` (PasswordAuthentication
  and KbdInteractiveAuthentication no). Verified: fresh key login works,
  password-only client gets `Permission denied (publickey)`. Applied while the
  exo session was live — sshd is socket-activated on macOS, so existing sessions
  were untouched.
- tailscale-gw: the `hft-bot-direct-no-1password` key is commented out pending an
  owner decision (backup `authorized_keys.bak-hftbot-*`). It is reversible with a
  one-line uncomment; no local cron/LaunchAgent references it.

## Patch plan (Fable-reviewed) and why PVE is on hold

Order: disposable Tanium client as canary → media-ingest-02 → remaining CTs
(snapshot first where the storage allows) → PVE nodes one at a time, install only.

**Done 2026-10-19** (each CT snapshotted as `pre-patch-20261019`, then
`apt-get dist-upgrade`; every host verified `pending=0` afterwards):
canary `tc-oracle8` (dnf, 104 → 0), then CTs 100 authentik, 101 tailscale-gw,
102 dns-01, 103 lb-01, 104 mail-01, 105 ntp-01, 106 vm-01, 107 graf-01,
108 proxy-01, 113 hermes-gw-01, 116 media-ingest-01, 117 media-ingest-02,
118 adblock-proxy-01, 170 frigate-01. Service checks after each: nginx, AdGuard
proxy units, authentik containers (health 200), hermes units (dashboard 302),
media-ingest collector, frigate docker, tailscaled with both routes still
advertised, cluster still quorate.

Two things surfaced during the run:

- **Grafana 12.3.1 → 13.2.4** (the dist-upgrade jumped a major). 13 refuses to
  start with the shipped default `[rendering] renderer_token`, so graf-01 came up
  failed until the token was set. Fixed forward with a 48-char token in
  `grafana.ini` and `AUTH_TOKEN` on the renderer unit; the role now carries it
  from the vault (`vault_grafana_renderer_token`) so a redeploy reproduces the
  working state. Health 200, only the two benign boot-time unit failures remain
  (`nvmf-autoconnect`, `openipmi`).
- **Pre-existing, not caused by the patch:** `adguard-log-shipper` on
  adblock-proxy-01 has failed 1370 times in 7 days — it gets HTTP 403 on the
  Home Assistant websocket handshake at 192.168.86.2. Separate fix.

**Still pending:** the three PVE nodes (81 packages each, including 4 from the
corosync / pve-cluster / pve-manager family) and the 12 remaining Tanium test
clients (35–104 each).

Blocker on PVE: `ha-manager status` shows the LRM active with watchdog on
pve02/pve03. A corosync restart with HA enabled can watchdog-fence (reboot) a
node, which is a reboot without the owner's word. So PVE installs wait for a
maintenance window; kernels land but take effect only at the next reboot, which
is also his call.

