# roles/alloy

Grafana Alloy — the unified telemetry agent. Replaces Promtail (logs)
and node_exporter (metrics) on every managed host except the Tanium
appliances.

## What it does

- Installs the `alloy` package (apt for Debian/Ubuntu, dnf for RHEL 9+,
  dnf-via-shell for EL8 — python3.9 lacks the dnf bindings ansible's
  `dnf` module needs, zypper-via-shell for SUSE).
- Renders `/etc/alloy/config.alloy` from `templates/config.alloy.j2`
  with the host-level metric exporter + journal log scraper +
  remote-write to vm-01 (VictoriaMetrics) and Loki push.
- Configures CLI args via `/etc/default/alloy` (Debian) or
  `/etc/sysconfig/alloy` (RPM-based) — same content either way.

## Key variables (`defaults/main.yml`)

- `alloy_version` — Renovate-tracked against `grafana/alloy` releases.
- `alloy_listen_addr` — the alloy management UI port (defaults
  `127.0.0.1:12345`, loopback only).
- `loki_url`, `vm_remote_write_url` — push endpoints, derived from
  `hostvars['vm-01']['ansible_host']`.
- `alloy_external_labels` — empty by default; override to `{agent: alloy}`
  when running a parallel deploy alongside the legacy stack.

## Metrics-only hosts

`alloy_ship_logs` (default `true`, set per-host in
`inventory/proxmox.yml`) toggles whether `config.alloy.j2` renders the
`loki.source.journal`/`loki.write` blocks at all. When `false`, only
the `prometheus.exporter.unix` metrics block ships — plain host
resource counters (CPU/mem/disk/net), no process names, no
command-lines, no journal content whatsoever. Use this for a host
where NOTHING in its journal is safe to ship (e.g. it has no units
worth alerting on beyond ssh/cron anyway, or you haven't yet audited
its logs).

## Unit-allowlist log shipping

`alloy_log_unit_allowlist` (unset by default, set per-host in
`inventory/proxmox.yml`) restricts journal shipping to only units whose
name matches the given regex — everything else is dropped inside Alloy
via a `loki.relabel` `action = "keep"` rule, before it ever leaves the
box. Use this when a host has some units worth real log-based alerting
(ssh brute-force, cron failures, mail delivery) alongside other units
that produce genuinely sensitive content.

Used for `media_ingest`/`media_ingest_02`/`media_gallery` (added
2026-08-05, upgraded from `alloy_ship_logs: false` the same day once
each host's actual journal content was audited via `journalctl`): these
CTs run a secondary-source scraper/gallery pipeline that's deliberately
obfuscated in this public repo (see `roles/media_ingest_02_host` and
the `git-history-identity-scrub` skill). Verified live — the
scraper/collector/gallery service units on all 3 hosts log the actual
sensitive detail (scrape-target usernames, chat IDs, folder/person
names) on nearly every INFO line, not just occasionally, so those
specific units are NEVER allowlisted. `ssh`, `cron`, `postfix`,
`systemd-journald` (and `kill-switch` on media-ingest-02 — a firewall
oneshot unit with no sensitive content) ARE allowlisted per-host — real
signal, zero leak risk, since none of those units ever reference
platform/username/content detail.

Set `alloy_log_unit_allowlist: '^(unit1|unit2)\.service$'` under a
host's `vars:` in `inventory/proxmox.yml`. Before adding a new unit to
any host's allowlist, audit its actual journal output first
(`journalctl -u <unit> -n 100`) — don't assume a unit is safe from its
name alone.

Both mechanisms live in `inventory/proxmox.yml` (NOT globally in
`defaults/main.yml`) — these are per-host security decisions, not
fleet defaults.

## Where it's invoked

`deploy_monitoring.yml` plays 2 (Install Telemetry Agents), 3 (Configure
VictoriaMetrics → vm-01), and 4 (Configure Grafana → graf-01).

## Migration history

See `docs/promtail-to-alloy-plan.md` for the migration that retired
`roles/promtail/` and `roles/common_monitoring/`.
