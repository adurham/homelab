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
| Unknown authorized keys | pve01/02/03 `amd` | **Dropped 2026-10-19** on owner's word: the `Tanium Macbook` RSA on all three nodes and the uncommented ECDSA on pve01. Each node keeps exactly three keys (sk, 1Password RSA, ansible). Backups `authorized_keys.bak-keydrop-*`. |
| Pending updates | fleet + 3 PVE | **Done 2026-10-19** for every service host and all three PVE nodes (0 pending). Only the Tanium test clients remain, blocked by segment egress (`Could not resolve host` / `Unable to connect`), not by policy. |
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
- **`adguard-log-shipper` on adblock-proxy-01 — fixed 2026-10-19.** Root cause
  chain: the HA long-lived token in
  `/etc/adguard-log-shipper/hass_token` was the pre-rotation one (the refresh
  token behind it no longer exists after the 2026-10-18 rotation), so every run
  failed auth; after five failures HA banned the container's LAN leg
  `192.168.86.41`, and from then on *every* request from that host — even with a
  valid token — got `403: Forbidden` from the ban middleware. Fix: removed the
  stale ban from `/config/ip_bans.yaml` (backup taken) and reloaded HA core, then
  replaced the token file with a valid JWT for the live refresh token. Loki now
  has fresh `job="adguard"` streams. Note: HA long-lived tokens are HS256 JWTs
  whose `iss` is the refresh-token id and whose signing key is that entry's
  `jwt_key` in `.storage/auth`, so a valid token can be minted offline without
  the UI.

**PVE nodes — done 2026-10-19**, one at a time, install only, `NEEDRESTART_MODE=l`:
pve01 → pve02 → pve03, each `apt-get dist-upgrade` rc=0, then verified quorate,
`pveproxy`/`pvedaemon`/`pve-ha-lrm`/`corosync` all active, 0 failed units, and
all three now report `pending=0`. Fencing stayed armed throughout and no node
was fenced; the CRM master moved pve03 → pve01 during the run as expected.
Kernel `7.0.14-25-pve` is installed on all three but they still boot
`7.0.14-15-pve` — reboot pending, owner's call.

**Tanium test clients — blocked, not a security gap.** Ten of the eleven can't
reach their package repos: `tc-ubuntu24` gets "Unable to connect to
archive.ubuntu.com", `tc-rocky9` "Couldn't resolve host mirrors.rockylinux.org".
The Tanium lab segment has no direct egress (it is documented as going through
proxy-01), so their 35–104 pending updates cannot be fetched without a network
policy change. Only `tc-oracle8` (the canary) and `tc-oracle9` reached 0.


## Second sweep (2026-10-20) — regressions found and fixed

The re-run audited 33 hosts (frigate-01 and hermes-gw-01 flaked on the pass but
were fine when probed directly). Headline results were clean: zero hosts with
SSH password auth, every key file down to its intended set, all service hosts at
0 pending packages. Two real regressions surfaced during the pass.

### P1 — ZFS replication and HA migration were broken since the sudo conversion

`pvesr status` showed every replication job failing with `exit 255` (44
consecutive failures) on `ssh root@172.20.0.x ... pvesr prepare-local-job`.
Cause: the PVE root-SSH policy applied during the 2026-10-19 conversion used
`Match Address 192.168.86.11,192.168.86.12,192.168.86.13` only. Proxmox runs
replication over the sync VLAN (`172.20.0.0/24`) and live migration over the
migrate VLAN (`172.21.0.0/24`), so both paths were refused root login. HA
failover would have failed the same way.

Fix: `Match Address ... ,172.20.0.0/24,172.21.0.0/24` (both VLANs have no
gateway and are confined to switch ports 3/4/5). Verified: root SSH over both
VLANs works and `pvesr run --id 103-0` completes `OK, FailCount 0`.
Codified in `harden_network_stack.yml`.

### P1 — SDN-wide internet egress outage from the nftables package upgrade

Every container ran Debian's default `nftables.service` (`flush ruleset`, empty
chains) while the real state is iptables rules applied by the roles and saved by
netfilter-persistent. The upgrade restarted the service, whose
`ExecStop=/usr/sbin/nft flush ruleset` wiped tailscale-gw's three MASQUERADE
rules. Result: the whole `172.16.0.0/24` SDN lost egress for about an hour,
`dns-01` kept answering authoritative queries but every recursion timed out, and
`hermes-gw-01` + `gallery-01` lost DNS (MagicDNS-only resolv.conf), their
tailscaled went offline and they became unreachable over the tailnet.

Fix: re-added and persisted the three MASQUERADE rules; masked `nftables.service`
on all 15 containers; replaced `/etc/nftables.conf` with a rules-free no-flush
file; restarted tailscaled on the two containers. Egress and recursion verified.
Codified in `harden_network_stack.yml` so a new CT cannot reintroduce it.

Still open from this incident: tailscale-gw's own `ts-*` chains were also wiped
by the flush (`iptables -S | grep ts-` = 0). Traffic still flows on a permissive
policy; recreating them needs a tailscaled restart on the gateway (brief tailnet
blip) — owner's word.

### Patches

Tanium test clients re-patched now that egress is back: 10 of 11 at 0 pending
(one pre-existing benign mount-unit failure each on rocky8/alma8/rhel8), plus
`tg-harvester-01` at 0. The remaining pending work is now zero across the fleet.

### Post-crash re-verification (2026-10-20, ~10:00-10:30) and the monitoring gap closed

The MacBook running the sweep died at 09:58 (WindowServer userspace watchdog
timeout, the second one in 40 seconds, after a 09:41 Jetsam event; it came back
at 10:00). No sweep work was lost — this doc and `harden_network_stack.yml`
were already committed at 09:49. Everything was re-verified live afterwards:

- **Replication was still showing FailCount 44 on ten jobs.** The SSH fix was
  real (root over the sync VLAN from pve01 to pve03 answered `ROOT_OK`), but
  Proxmox keeps the failure counter until a job actually completes, and the
  scheduler had not reached them yet. Ran every pending job by hand
  (`pvesr run --id ...`): 103-0/103-1/104-0/104-1/106-0/106-1/107-0 all ended
  with `end replication job`, and `pvesr status` now reports **FailCount 0 on
  all 14 jobs** (113-0 was mid-sync, also 0). FailCount 0 is the state that
  matters — a stale counter is exactly how "replication broken for N days"
  hides.
- **Egress and recursion from inside the SDN**: `dns-01` fetched
  `https://example.com` → 200 in 0.18 s and resolved `google.com`
  recursively. `nftables.service` is `masked` + `inactive` there.
- **tailscale-gw**: 3 nat `POSTROUTING` MASQUERADE rules present (2x
  `172.16.0.0/24` for eth0 + tailscale0, 1x `10.99.0.0/24`), nftables masked,
  tailscaled active. The `ts-*` iptables chains were **0** at that point,
  still missing from the nftables flush.
- **tailscaled restarted on tailscale-gw 15:37 UTC (owner-approved).** Chains
  came back within 5 s (`-N ts-forward`, `-N ts-input`), tailscaled active,
  self online with the same two advertised routes (`10.99.0.0/24`,
  `172.16.0.0/24`), 12 tailnet peers visible. Post-restart from inside the
  SDN: peer `100.119.249.49:22` open, external HTTPS 200, dns-01 recursion
  answering — so the subnet-router path survived the restart. The three
  MASQUERADE rules were untouched (the restart only rebuilds tailscaled's own
  chains). `tailscale_gw_ts_iptables_chains` now reports **2**.

**New monitoring (this closes "an hour of total egress loss alerted nothing").**
Three blackbox jobs on vm-01, all verified returning `probe_success 1` live:

| job | module | target | catches |
| --- | --- | --- | --- |
| `blackbox_internet_egress` | `https_204_egress` | google `generate_204` + cloudflare `cdn-cgi/trace` | SDN-wide egress loss (vm-01's default route is tailscale-gw) |
| `blackbox_dns_recursion` | `dns_recursion` | `172.16.0.10` (dns-01) | authoritative-answers-but-no-recursion |
| `blackbox_tailnet_nodes` | `ssh_banner` | `100.119.249.49:22`, `100.83.114.12:22` | hermes-gw-01 / gallery-01 falling off the tailnet |

Plus `roles/nat_metrics` on tailscale-gw: a 60 s timer writing
`tailscale_gw_nat_masquerade_rules`, `..._sdn_masquerade_rules`,
`tailscale_gw_ts_iptables_chains` and `tailscale_gw_nftables_service_active`
into the textfile collector (Alloy ships them; `textfile_collector_enabled:
true` on that host). Live values: 3 / 2 / 0 / 0.

Four Grafana rules provision alongside them (`sdn_egress_down`,
`dns_recursion_down`, `tailnet_node_unreachable`,
`nat_masquerade_rules_missing`) — 57 rules total now loaded, scheduler running
all four with no evaluation errors.

**Two automation defects found while deploying this, both fixed:**

1. **The Grafana play could never finish, which silently blocked every new
   alert rule.** `Clone Grafana Image Renderer` failed with git's "dubious
   ownership" (checkout owned by `grafana`, the module's remote-URL step
   running with root's uid) — and that task sits *before* the alerting
   provisioning tasks, so the play aborted and no rule ever deployed. Added a
   `safe.directory` declaration for that path (git's own supported fix,
   idempotent).
2. **The alloy role tried to downgrade hosts that had drifted ahead.** The
   install test was "pinned version string not in installed version string",
   so graf-01 (1.20.1) was told to install 1.16.0, apt refused ("A later
   version is already installed") and the whole play aborted. It now installs
   only when alloy is missing or *older* than the pin.

Also worth knowing for the next person: Grafana reads file-based alerting
provisioning **only at startup**. Compare
`systemctl show grafana-server -p ExecMainStartTimestamp` with the mtime of
`/etc/grafana/provisioning/alerting/rules.yml` before debugging a rule that
"didn't deploy" — that mismatch was the actual state here until 15:25.

**Still open (owner's word):** the node-by-node PVE kernel switchover —
deliberately deferred; the tailscaled restart above is done.

## Third sweep (2026-10-20, 10:35-11:05) — relationships, not boxes

Scope widened after a Fable review: sweeps 1-2 were host-config audits, but
both real incidents were *relationship* failures (sshd Match vs. VLANs,
patch run vs. NAT state). This pass therefore tested paths and credentials:
who holds what, what trusts what, and what is reachable from where.

Method: `ansible/files/lab_audit.sh` (35 hosts) plus `sec_audit.sh`
(identity/keys/secrets/IPv6), `lxc_audit.sh` (privilege boundary, per node),
`pve_identity_audit.sh` / `pve_backup_audit.sh` (PVE users, tokens, ACLs,
backups), HA via the SSH add-on, edge via `nginx -T`, external vantage via
check-host.net. All four scripts are now in the repo — the sweep-2 script
lived in `/tmp` and the MacBook crash destroyed it, so the numbers could not
be reproduced.

### Confirmed still good

- Key-only SSH on all 35 reachable hosts (`PasswordAuthentication no`,
  `PermitEmptyPasswords no`, `MaxAuthTries 6`).
- Fleet sudo gate holds: every gated host has exactly **one ED25519-SK key**
  in `/etc/security/sudo_keys/amd`, `amd`'s password is **locked**, no
  plain-key fallback exists. (The ansible RSA key is not in that file.)
- No non-root uid 0, no empty passwords, `root` is the only login shell
  account on the containers.
- 0 pending packages on every service host; 3 nightly PVE backup jobs all
  OK (10-20 07:00/07:30/08:00).
- PVE `root@pam` **does** have TOTP + recovery codes — sweep 1's "no TFA"
  note is stale and should not be repeated.
- Edge: unknown SNI → 444 on 80 and 443; no `real_ip`/XFF trust anywhere in
  `nginx -T` (so `X-Forwarded-For: 172.16.0.5` cannot fake internal).
  External check-host probes: `auth.` 302 public as designed, Tanium
  `/api/v2/session` 403 from DE/HU/RU.

### Findings, ranked
| # | Finding | Why it matters | Owner input? |
| - | - | - | - |
| 1 | ~~HA Cloud remote access enabled with zero MFA~~ — **NOT A FINDING (corrected by owner, 2026-10-20)** | HA login is OIDC through Authentik with a Require-MFA policy bound, and the local `root` account carries TOTP; Nabu Casa's relay does not add an MFA step of its own but lands on that MFA-protected login. The sweep's `mfa_modules` probe read the wrong storage key and reported 0. | none |
| 2 | **`root@pam` API token `hermes-automation`: `privsep=0`, no expiry** | Full cluster-root API rights; PVE tokens bypass TFA. It is the highest-privilege credential in the lab | yes — migrate to a least-privilege user/token (note PVE forces `root@pam` for raw `lxc.*`/device/mp CT ops) or at minimum set an expiry |
| 3 | **`tailscale-gw` is the only privileged LXC** (`unprivileged: 0`) — and it is the perimeter host that terminates tailnet traffic and owns the SDN NAT | Privileged container = no real boundary; compromise of the most exposed guest is pve02 root | yes — convert (backup, `pct restore --unprivileged`, tun passthrough, rollback keeps 101) or a small dedicated VM |
| 4 | **`frigate-01` is the only host with a global IPv6 address** (`2600:1702:768c:9cf::/64`) + default route via RA; go2rtc listens wildcard on 1984/8554 with no auth | If the AT&T gateway does not filter inbound v6, that is a direct bypass of the whole edge. Also the only guest bridged to the physical LAN | yes — confirm from cellular, and/or disable IPv6 on the container (it has no need) |
| 5 | **`nftables.service` only `disabled` on pve01/02/03** (masked on all 13 containers) and **`enabled+active` on 4 Tanium test clients** | Exactly the service whose `ExecStop` (`nft flush ruleset`) killed SDN egress yesterday. On a PVE node it would flush pve-firewall's ruleset | no — masking on PVE is trivial guard-rail codification; the Tanium clients need `/etc/nftables.conf` read first (it may be their only firewall) |
| 6 | **Two undocumented listeners on pve01**: `/root/boxhelp/srv.py` on `0.0.0.0:8001` and `nc -l -p 8002`, both started 2026-10-18 23:32/23:34, no connections since | Raw TCP listener on a hypervisor; an unexplained one is an incident until explained | yes — triage was blocked mid-run (needs an approval); is `boxhelp` yours and does 8002 need to stay? |
| 7 | **`hermes-token-check.service` failed** on hermes-gw-01 | The daily Claude OAuth-expiry check is dead — silent capability loss, not a security breach | no — investigate/fix |
| 8 | Tailnet: **no tags on any node**, 14 peers — **all now attributed by the owner (2026-10-20)**: `MLHVYY0PWXMN` is the corp work MacBook, the two iOS devices named `localhost` are the owner's and Tati's phones (Tati's account is suspended, so that device is restricted). No unknown peers. | `100.64.0.0/10` is classed internal by the edge geo map, so tailnet membership *is* LAN membership — that is fine while every peer is a known owner device, and worth re-checking whenever a peer is added. Missing tags only matters if the ACL should be tag-scoped later. | none — closed |
| 9 | `X11Forwarding yes` fleetwide; `homeassistant.local` `PermitRootLogin yes` (SSH add-on, key-only) | Hygiene only; no exploit path with key-only auth | no — fold into the sshd drop-in |

### Audit-script correction

Sweep 3's first pass reported `ssh_fail_24h=6066` on vm-01 and `1298` on
graf-01. **Both were false positives**: the grep matched Loki/Grafana log
lines that *quote* the alert query string `|~ "Failed password|Invalid
user"`, and only the two hosts running the log pipeline showed them. Real
count with `grep -E '\ssshd\[[0-9]+\]:.*Failed password'`: **4 on vm-01 in
24h, 0 elsewhere**. The script is fixed.

**Unreachable (18):** the BWT lab segment (10 hosts), the three TanOS
appliances' management names, and `tc-debian11` — unchanged from sweep 2 and
consistent with those segments being deliberately isolated. They remain the
one part of the estate with no sweep coverage at all.


### Sweep 3 — what was actually changed (2026-10-20, 11:00-11:35)

| # | Action | Verified |
| - | - | - |
| 2 | **Revoked `root@pam!hermes-automation`.** Nothing consumed it: no role, playbook or gateway config referenced `vault_proxmox_api_token_*`, and the token id appears **0 times** in both the live and rotated `pveproxy` access logs. `pveum user token list root@pam` is now `[]`, and the vault block is replaced by a revocation note (the dead secret is still in 1Password item `felm6nfoibmszrus2ftoubx4n4` — drop it at the next edit). | token list empty; `grep -c '^vault_proxmox_api_token'` = 0 in the vault |
| 4 | **IPv6 disabled on frigate-01** (sysctl drop-in `/etc/sysctl.d/99-disable-ipv6.conf`, `accept_ra=0`). It was the only guest with a router-advertised global address; frigate has no IPv6 need and go2rtc's unauthenticated 1984/8554 were listening wildcard. | `gua_count=0`, `eth0` IPv4-only, nginx still 200 |
| 5 | **`nftables.service` masked on pve01/02/03** and codified in `harden_network_stack.yml`. Deliberately *not* applied to the Tanium test clients: there `/etc/nftables.conf` **is** the live firewall (12-19 rules, unit enabled+active), so masking would mean stopping it and losing their only policy. | `systemctl is-enabled nftables` = masked on all three nodes |
| 6 | **Closed the two pve01 listeners.** They were *ours*: `/root/boxhelp/srv.py` is "tiny file server for the amd-workstation rescue session" (systemd-run unit `boxhelp`, serving `r.sh`/`rfix.sh` and accepting `POST /report`) and `boxhelp-nc` was a `while true; do nc -l -p 8002 >> report-nc.txt; done` sink. Left over from 2026-10-18 23:32 and never cleaned up. Both units stopped, both ports closed; `/root/boxhelp` kept as evidence for the workstation debugging. | `ss -lntp` shows 8001/8002 closed, no `boxhelp*` units |

**#3 (privileged LXC) was attempted and aborted — and the attempt exposed a fact
the earlier sweeps got wrong.** CT 101 is **HA-managed** (`ha-manager status`
lists `ct:100`, `ct:101`, and ten more). `pct stop` therefore goes through the
CRM, which **live-migrated the gateway from pve02 to pve01** while the restore
was refused ("can't overwrite running container"). Nothing broke: the gateway
came up on pve01 with `tailscaled` active, all three MASQUERADE rules, both
advertised routes, SDN egress 200 and recursion answering; the tailnet-liveness
probes went 0 for ~2 minutes during the migration and returned to 1 by
themselves. But a same-VMID `pct restore --unprivileged 1` cannot be done
against an HA-managed guest without first taking it out of HA, and the backup
archive sits on node-local `vzdump-nvme`, which pins the restore to whichever
node holds it. That is a maintenance-window procedure, not an ad-hoc one.

Recommendation stands, with a better endpoint than a conversion: **replace the
gateway with a small dedicated VM** (real privilege boundary, no tun/module
caveats, HA-able) rather than converting the LXC. If conversion is preferred,
the order is: `ha-manager set ct:101 --state stopped` → wait for stopped →
`--state disabled` → restore on the node that holds the archive → start →
`--state started`.

`ansible/files/convert_tailscale_gw_unprivileged.sh` carries the attempt and its
rollback path; it now aborts unless the HA resource is out of the picture first.
