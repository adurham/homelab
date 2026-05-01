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

## Where it's invoked

`deploy_monitoring.yml` plays 2 (Install Telemetry Agents), 3 (Configure
VictoriaMetrics → vm-01), and 4 (Configure Grafana → graf-01).

## Migration history

See `docs/promtail-to-alloy-plan.md` for the migration that retired
`roles/promtail/` and `roles/common_monitoring/`.
