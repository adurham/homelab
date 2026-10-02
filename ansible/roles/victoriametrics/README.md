# roles/victoriametrics

VictoriaMetrics (Prometheus-compatible TSDB) on vm-01. Receives metrics
pushed by Alloy (every managed host) and pulled from its own
`blackbox_exporter` scrape jobs (Tanium postgres/console, cert expiry,
iframe checks) defined in `prometheus.yml.j2`.

Note: the Tanium appliances (`tanium_cluster`) run **no** monitoring
agent — the old `:9100` node_exporter scrape job was retired 2026-08-09
(TanOS default-deny iptables never exposed the port, and these vendor
appliances run no custom software). Tanium host-down detection now comes
from the agentless `blackbox_tanium_reachable` TCP/22 probe.

## What it does

- Downloads the upstream binary (`victoria-metrics-prod`) from the
  GitHub releases pinned by `victoriametrics_version`.
- Renders the systemd unit + scrape config (`prometheus.yml.j2`).
- Sets `-retentionPeriod=2y` (two years of metric history; coupled with
  blackbox/loki disk pressure alerts).
- Configures blackbox probe targets for: HTTPS cert-expiry on the
  public-facing endpoints (`blackbox_https_targets`), Tanium postgres
  (5432/5433), Tanium server consoles (:443).

## Key variables (`defaults/main.yml`)

- `victoriametrics_version` — Renovate-tracked against
  `VictoriaMetrics/VictoriaMetrics` releases.
- `blackbox_https_targets` — list of HTTPS URLs to probe for cert/probe
  alerts.

## Where it's invoked

`deploy_monitoring.yml`'s play `Configure VictoriaMetrics` (play 8), along
with `pve_exporter`, `blackbox_exporter`, `loki`, `alloy` and `vm_backup`.
