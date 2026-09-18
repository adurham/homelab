# 2026-09-10 Fleet Health Sweep

Full record of an extended, open-ended homelab audit that started from a
single reported symptom (Hue Play sync box "blip") and expanded, per
standing instruction ("keep sweeping"), into a fleet-wide health pass
across Proxmox, the CT/VM fleet, Home Assistant, monitoring/alerting, and
network/DNS. This document is the durable record; git commit messages
carry the mechanical detail per change.

Commits this session (chronological): `2ae252f`, `36e833e`, `bac1076`,
`445ca41`, `6177dee`, `628a33e`, `3c39f73`, `a4d6783`, `bf12a80`,
`b88325d`, `1c9194d`, `08c67ff`, `8fbb145`, `a0f32bb`.

## 1. Origin: Hue Play HDMI sync box "blip"

Root cause was an internal coordinator hang inside the sync box itself,
not a network/Zigbee/HA issue. Fixed via a power-cycle plus a new HA
watchdog automation (`homeassistant/automations/entertainment/
game_room_sync_box_watchdog.yaml`) so a repeat doesn't need manual
intervention.

## 2. Logging & backup hygiene (commit `2ae252f`, `445ca41`)

- Built `roles/logrotate/` (two mechanisms: logrotate for fixed-name
  logs, an age-based prune script+timer for media-ingest's dated-
  directory tree). Deployed fleet-wide.
- Discovered **zero Proxmox backups existed anywhere in the cluster** --
  no vzdump jobs, no PBS, nothing. Created 3 staggered nightly vzdump
  jobs (pve01 02:00, pve02 02:30, pve03 03:00; snapshot mode, zstd,
  keep-last=3). Proved the backups actually restore: live-backed-up
  Authentik, restored to an isolated test CT, confirmed all 4 containers
  came up healthy and the web app responded.
  - Known, accepted gap: **pve03 has no off-node copy** of its backups --
    user explicitly declined this follow-up ("not doing that right now").
    Do not re-raise.
- Found no generic "systemd unit failed" alert existed anywhere (root
  cause of chrony sitting silently dead 3 days on pve03 earlier in the
  session). Enabled Alloy's systemd collector, added the
  `systemd_unit_failed` Grafana rule, live-fire tested with a synthetic
  failing unit, and excluded known-benign LXC boilerplate noise
  (`ifupdown-wait-online`, `networking`, `nvmf-autoconnect`, `openipmi`)
  to avoid alert fatigue.

## 3. pve03 root cause (investigation only, no fix -- hardware)

Root disk `/dev/sda` is a spinning Seagate ST500LM021 laptop HDD (not
the NVMe boot/data disk), 112 reallocated sectors, 17,558 power-on
hours. Traced 8+ unclean reboots since January 8 2026 to this failing
disk. **User's explicit standing instruction: this is a known hardware
issue, don't fix it right now, don't re-raise it, work around it.**

## 4. Network identity fixes

- **tailscale-gw**: found via unreachability during a fleet-wide ansible
  ping sweep. Root cause: inventory documented a static IP but the
  interface was actually DHCP; the real lease had drifted (`.32` ->
  `.82`). Band-aid: corrected inventory (`6177dee`). Root fix: converted
  the CT to a genuine static IP, `192.168.86.16`, chosen outside AdGuard
  Home's documented DHCP pool (`.20`-`.250`) -- confirmed safe via nmap
  since ICMP is blocked/deprioritized on this LAN (`3c39f73`).
- **tc-debian11**: stale ifupdown state vs kernel (networking.service
  reported active, interface had no IP). Fixed live with
  `ifdown eth0 && ifup eth0`. Swept all other tc-* hosts -- confirmed
  isolated, not a fleet pattern.

## 5. ZFS scrub scheduling + fleet-wide security patching (`628a33e`)

- ZFS scrub had never been scheduled anywhere (timers ship disabled,
  last real scrub was Aug 9). Added per-node scheduling vars, fixed an
  invalid `OnCalendar` day-of-month syntax bug before it shipped broken,
  deployed, verified staggered across all 3 nodes, ran immediate manual
  scrubs on user's approval (all clean, 0 errors).
- Built `roles/unattended_upgrades/` for CT-wide security patching (pve
  nodes already had this via a separate role; no CT anywhere did).
  Found and fixed a real bug before shipping: the template copied
  Debian's `Origins-Pattern` directive onto a mostly-Ubuntu fleet, which
  uses `Allowed-Origins` -- would have silently matched zero packages
  forever, looking deployed while doing nothing. Made the template
  distro-conditional. Deployed to 17-19 hosts, verified live on
  Authentik (85 real security packages queued, ran for real, all
  installed cleanly, containers stayed healthy).
  - `tanium_clients` (tc-*, RPM/SUSE) intentionally excluded --
    **user has confirmed this is permanent and correct, not a gap.**

## 6. Cleanup: 33GB orphaned ISO on pve01

`/var/lib/vz/template/iso/tanium_bak_transfer_254.iso` -- confirmed
unreferenced by any VM/CT config anywhere, user-approved, deleted.
pve01 disk 70% -> 33%.

## 7. Two separate orphaned monitoring-stack leftovers on mail-01

- **VictoriaMetrics** (running since Jan 15 2026, matching the exact
  commit date the real monitoring stack was first built -- mail-01 was
  almost certainly the original prototype host, never cleaned up when
  the stack moved to vm-01). 14GB, driving disk to 78%. Confirmed zero
  references anywhere, removed. Disk back to 5%.
- **Loki + blackbox_exporter** (running since May 2026 -- a separate,
  later incident from the VictoriaMetrics one). Same pattern, same
  fix: confirmed unreferenced, removed cleanly, Postfix unaffected
  throughout.

## 8. Authentik: critical CVE + version currency (commit inline, no repo change --
operational/live-state)

Found Authentik pinned at `2025.8.1`, ~12 months stale, vulnerable to:
- **CVE-2026-25227** -- critical, CVSS 9.1, RCE via property-mapping
  test endpoint.
- CVE-2026-25748 -- auth bypass via forward-auth + malformed cookie.
- CVE-2026-25922 -- SAML auth bypass, CVSS 8.8.

Authentik enforces sequential major-version upgrades (no skipping).
Took a fresh backup first, then walked the full required chain:
`2025.8.1` -> `2025.8.6` -> `2025.10.4` -> `2025.12.4` -> `2026.2.7` ->
`2026.5.6` -> `2026.8.0` (latest stable). Verified real functional
health at every hop (container status, `/health/ready`, `/health/live`,
the actual login-flow HTML, external redirect through the real domain)
-- not just "container is up". Zero real downtime. One cosmetic,
self-resolving worker-liveness log warning during the final hop,
confirmed non-functional.

Follow-up cleanup: the 6 old image versions pulled during the upgrade
chain were left on disk, pushing authentik to 69% used with 4.5G free.
Removed all 6 (kept only 2026.8.0), disk back to 33%.

**Known gap, not fixed**: Authentik's version isn't tracked in the
ansible repo at all -- lives purely in a `.env` file on the live
container that nothing templates. This is *why* it silently sat stale
for a year. Flagged for a future session, not built tonight (out of
scope for "patch the CVE").

## 9. TLS certificate near-miss (`bf12a80`)

lb-01's wildcard (`*.chi.lab.amd-e.com`) and `proxmox.chi.lab.amd-e.com`
Let's Encrypt certs had **silently stopped auto-renewing since July 23**.
Root cause: `DEDYN_TOKEN` (deSEC DNS API token, required for DNS-01
validation) vanished from `/root/.acme.sh/account.conf` on lb-01
sometime before Aug 21 -- exact trigger not identified. Every daily
cron renewal since then failed with "You did not specify DEDYN_TOKEN
yet", and since there's no log file configured (cron output goes to
`/dev/null`), this was completely silent.

Caught via a manual TLS cert-expiry sweep with **41 days of runway
left** (expiry Oct 21) -- the fleet's TLS for auth, grafana, and
proxmox's web UI would have gone down with zero warning otherwise.

Fixed live: re-issued both certs with the real token pulled from
vault (acme.sh auto-persists it back into `account.conf` on use, which
also fixes all future unattended renewals going forward), then manually
ran `--install-cert` for both (a raw `--issue` bypasses the nginx
deploy hook that `--renew`/`--cron` trigger automatically). Confirmed
via `openssl s_client`: both live-serving fresh certs valid to Dec 9
2026.

Also fixed a latent bug hit during recovery: the role's DNS
propagation wait (`--dnssleep`) defaulted to 120s, which is **not
reliably enough** for deSEC's public authoritative servers -- a manual
retry with 120s failed NXDOMAIN, an identical retry at 300s succeeded
immediately. Bumped the default to 300s with the whole incident
documented inline in the role.

## 10. Duplicate/conflicting security headers on nginx vhosts (`b88325d`)

Found via a live-firing Grafana alert (`admin_ui_iframe_self_blocked`,
active since Sep 6). Root cause: nginx's shared
`security_headers`/`security_headers_self_frame` blocks add
`X-Frame-Options`/`Content-Security-Policy` via `add_header` but never
strip the upstream app's own copies first -- Tanium's own app already
sets these, so nginx was appending duplicates with conflicting CSP
values on top. Some browsers reject duplicate/conflicting CSP headers
outright and silently fail to render (200 OK the whole time, no error
in nginx logs -- exactly the failure mode this file's own header
comment already warned about).

Fixed with `proxy_hide_header X-Frame-Options;` /
`proxy_hide_header Content-Security-Policy;` added to both header
flavors before the `add_header` directives. Verified clean on Tanium,
Proxmox, and Grafana (no regression on the strict DENY-flavor vhosts).

## 11. Live production outage: `ip_hash` sticky sessions hitting a dead node (`1c9194d`)

While chasing #10's alert further (it turned out headers weren't the
whole story), found the alert was STILL firing after the header fix.
Traced it to a second, unrelated, much more serious bug: nginx's
`tanium_servers` upstream uses `ip_hash` load balancing across
`ts-01` (working) and `ts-02` (a known/intentional standby, confirmed
by user as not a real gap). With `ip_hash`, any client IP whose hash
landed on `ts-02` was getting **permanently stuck retrying a dead
node for a full 60-second timeout on every single request** to the
Tanium console -- reproduced live from 4+ different hosts, including
this operator's own laptop over Tailscale (curl timing: 60.0s exactly,
every time, `start_transfer` phase). This was a real, currently-active
partial outage, not a monitoring artifact.

Fixed by marking `ts-02 down;` in the templated upstream block
(conditional on hostname, not removed from inventory, clearly
commented for when ts-02 comes back for real). Verified: all
previously-affected hosts now respond in 30-40ms, and the
`blackbox_iframe_self_ok` probe for tanium.chi.lab.amd-e.com reports
`probe_success 1` / HTTP 200.

## 12. Home Assistant: real safety gap on the pool pump

Found: `pool_season` was `on`, the pump was running its normal daily
schedule (7 hrs that day), but **both actual safety-cutoff automations**
(`pool_pump_safety_dead` -- no power draw / tripped breaker,
`pool_pump_safety_low_draw` -- dead-head / lost prime) were disabled at
runtime. Only the informational "sensor stale" companion was still on.
The dead-rule's `last_triggered` timestamp matched exactly to an Aug 19
false-trip incident already documented in the automation file's own
comments -- strongly suggesting it was switched off during that
debugging session and never re-enabled.

Pump happened to be off at the moment of discovery (past its scheduled
16:00 off-time), so nothing was actively at risk in that instant, but it
would have run fully unprotected against seal/motor damage on the very
next scheduled cycle. Re-enabled both automations live, per user
approval, confirmed state.

## 13. SSH access hygiene (6 hosts)

`proxy-01`, `media-ingest-01`, `media-ingest-02`, `hermes-gw-01`,
`gallery-01`, `frigate-01` all had a duplicated identical login-key
entry plus one old, unrecognized RSA key (label "Tanium Macbook", key
material not matching the current ansible-managed key, not referenced
anywhere in the repo). User confirmed neither was still needed.
Backed up `authorized_keys` on all 6 before editing, removed the
duplicate + the stale key on each, verified ansible/SSH access still
worked on all 6 afterward, then removed the backups.

## 14. Home Assistant: two dead-trigger automation bugs

- **AdGuard Home watchdog** (`08c67ff`): the self-heal automation's
  trigger entity (`binary_sensor.adguard_home_running`) has never
  existed on this HA instance -- confirmed via `/api/states`, "Entity
  not found". This automation has been silently dead code since
  creation, never firing once. (Alerting itself was fine -- the
  Grafana `adguard_dns_down` rule already worked around this exact
  problem back on 2026-08-09 by keying off a different, real entity.)
  Retargeted the HA-side automation to the same real entity
  (`switch.adguard_home_protection` going `unavailable`). Also
  confirmed AdGuard itself is genuinely healthy while investigating:
  18.91% block ratio across 2.17M DNS queries, manual dig tests for
  both normal resolution and ad/tracker blocking both pass.
- **Garage lights** (`8fbb145`): the right garage bay door's
  door-open trigger referenced a raw Shelly device-ID entity_id
  (`binary_sensor.shelly1minig3_b08184ee0fd0_garage_door`) that no
  longer exists in HA's entity registry -- likely stale from before
  the device got a friendly `entity_id`. Not a full outage (motion
  detection covered as a fallback trigger), but the door-open signal
  itself was silently inert. Retargeted to the real, live entity_id
  (`binary_sensor.right_garage_bay_garage_door`), matching the existing
  left/middle naming convention.

Both deployed via `ansible/deploy_ha_automations.yml` (config check
passed, hot-reloaded via API, no HA restart needed).

## 15. Exploratory pass: things checked and found clean

- **Fleet memory/swap**: all hosts comfortably under 50% memory used,
  no meaningful swap activity anywhere.
- **Load average**: several containers showed identical, seemingly
  alarming load numbers -- traced to a known LXC quirk (unprivileged
  containers report their *physical Proxmox node's* `/proc/loadavg`,
  not their own container-scoped load). All 3 nodes actually have
  large real headroom (pve01: 91G free of 125G RAM; pve02/03: 15-23G
  free of 62G each).
- **Docker image hygiene** elsewhere: frigate-01 clean (single current
  image, 0 reclaimable). No other host in the fleet runs Docker.
- **Discord alert delivery pipeline** (`grafana-ack-bot` on
  hermes-gw-01:8990): confirmed genuinely healthy -- 2 days uptime,
  zero real errors in 7 days of logs, all Discord API rate-limit
  retries succeeded within budget, 16/16 webhook POSTs today returned
  200, no dropped alerts (first check used the wrong systemd unit name
  and false-alarmed; real unit name is `grafana-ack-bot`, hyphenated).
- **HA integration "not loaded" list** (31 of 105 integrations):
  investigated because it included door locks and looked concerning --
  confirmed all 31 have `source: ignore`, meaning every one is a
  deliberately-dismissed device discovery (user clicked "Ignore" on a
  setup prompt at some point), not a failure of any kind.

## 16. Real monitoring gap closed after a `consult` second opinion (`a0f32bb`)

Ran out of concrete leads and used `consult` per standing practice.
Recommendation: verify whether the monitoring stack's own *absence* is
detectable, since every finding that mattered tonight (#9, #12, #14)
was exactly that shape -- a healthy-looking surface hiding a silent
failure underneath.

Investigation confirmed a real gap: the existing `dead_mans_switch`
Grafana rule (pings healthchecks.io externally) only proves Grafana's
own rule-evaluation engine and internet egress are alive -- its
expression is a constant `1` against the `__expr__` pseudo-datasource,
never touching VictoriaMetrics at all. It would have kept pinging out
successfully even if VM died outright, while all 21 other alert rules
(everything that depends on `datasourceUid: victoriametrics`) silently
had zero real data to evaluate against -- with no signal anything was
wrong.

Added `metrics_pipeline_dead`: queries VM for
`count(node_uname_info)` -- a real, always-present metric
remote-written by Alloy from every host in the fleet (~31 normally) --
and fires if it drops below 5, proving the *whole* pipeline (Alloy ->
VM remote-write -> Grafana query) is alive, not just Grafana's engine
in isolation. `noDataState`/`execErrState` both set to `Alerting`,
since a query returning nothing or erroring IS the exact failure this
rule exists to catch.

**Live-fire tested for real**: stopped `victoriametrics` on vm-01,
confirmed via Grafana's own rules API that the new rule transitioned
to `firing` (alongside the expected `DatasourceError` state on all 21
other VM-dependent rules) after ~6 minutes, restarted VM, confirmed
the rule cleanly resolved back to `inactive` once real data resumed.

## Known, intentionally-accepted gaps (do not re-raise without new information)

- **pve03's failing spinning disk** -- hardware, user declined
  replacement, working around it.
- **pve03 backups have no off-node/off-box copy** -- user explicitly
  deferred this follow-up.
- **`tanium_clients` (tc-*, RPM/SUSE) excluded from unattended-upgrades**
  -- user confirmed this is permanent and intentional, not a gap.
- **tms-01 hitting the wrong squid port** (SSL-bump instead of the
  passthrough port squid.conf already reserves for Tanium appliances,
  causing ~24,700+ TLS handshake failures/day in cache.log) --
  documented only, user said don't touch it (TanOS appliance, outside
  ansible's management scope, guest-exec disabled).
- **ts-02 / tms-02 (Tanium secondary server/module appliances) down**
  -- confirmed by user as a known, intentional standby-incomplete
  state, not a gap. (Note: this WAS the underlying cause of #11's
  ip_hash outage -- that fix stands regardless of ts-02's own status,
  since nginx-side load-balancing correctness doesn't depend on
  whether ts-02 is ever brought back up.)
- **Tati's phone WiFi presence tracking stale since Sep 6** (her
  nmap_tracker entity fully disappeared, consistent with an iOS
  private-MAC-address rotation) -- user is handling her own device
  settings personally, not to be touched.
- **Authentik's deployed version isn't tracked in the ansible repo** --
  real gap, flagged, not built tonight (separate scope from tonight's
  CVE patch).

## Verification standard used throughout

Every fix in this document was confirmed with real evidence before
being called done -- not "container is up" but the actual functional
behavior: HTTP status codes, TLS certificate `notAfter` dates read
directly via `openssl s_client`, live alert-rule state transitions
via Grafana's own APIs, `curl` timing breakdowns, `dig` against public
authoritative DNS, and (for the ip_hash outage and the
metrics-pipeline dead-man's-switch) actual live-fire reproduction --
i.e., breaking the real thing on purpose and watching the fix catch
it, then restoring it and confirming recovery.
