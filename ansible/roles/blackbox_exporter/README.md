# roles/blackbox_exporter

Prometheus blackbox_exporter on vm-01 — runs TCP and HTTPS probes that
back the `tanium_postgres_unreachable`, `tanium_console_unreachable`,
`https_endpoint_unreachable`, and `cert_expiring_soon` /
`cert_renewer_wedged` Grafana alerts.

## What it does

- Downloads `blackbox_exporter` binary from upstream releases.
- Renders `/etc/blackbox_exporter/blackbox.yml` with two modules:
  - `tcp_connect` — TCP connection check (used for postgres + Tanium
    console probes).
  - `https_2xx` — HTTPS GET that emits `probe_ssl_earliest_cert_expiry`
    so cert-runway alerts work. `fail_if_not_ssl` enforces the cert
    actually exists.

## Key variables (`defaults/main.yml`)

- `blackbox_exporter_version` — Renovate-tracked against
  `prometheus/blackbox_exporter`.

## Probe targets

Defined in `roles/victoriametrics/templates/prometheus.yml.j2`'s
`blackbox_*` jobs (this role just installs the prober; targets live
with the scraper config). `blackbox_https_targets` in
`roles/victoriametrics/defaults/main.yml` is the HTTPS list.

## Where it's invoked

`deploy_monitoring.yml`'s play 3, alongside `victoriametrics` and `loki`.
