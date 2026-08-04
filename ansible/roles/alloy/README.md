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
command-lines, no journal content whatsoever.

Used for `media_ingest`/`media_ingest_02`/`media_gallery` (added
2026-08-05): these CTs run a secondary-source scraper/gallery pipeline
that's deliberately obfuscated in this public repo (see
`roles/media_ingest_02_host` and the `git-history-identity-scrub`
skill) — platform/username/chat details could leak into the shared
Loki instance via process output or error traces if journal shipping
were enabled, even though Loki is internal-only. Metrics don't carry
that risk (a CPU/network counter can't reference a username), so those
three hosts get real perf visibility (previously zero — they were
excluded from Alloy entirely 2026-07-27 through 2026-08-04) without
reopening the log-leak concern that got them excluded in the first
place.

Set `alloy_ship_logs: false` under a host's `vars:` in
`inventory/proxmox.yml` (NOT globally in `defaults/main.yml` — this is
a per-host security decision, not a fleet default) to apply the same
pattern to a future sensitive host.

## Where it's invoked

`deploy_monitoring.yml` plays 2 (Install Telemetry Agents), 3 (Configure
VictoriaMetrics → vm-01), and 4 (Configure Grafana → graf-01).

## Migration history

See `docs/promtail-to-alloy-plan.md` for the migration that retired
`roles/promtail/` and `roles/common_monitoring/`.
