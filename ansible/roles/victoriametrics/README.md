# roles/victoriametrics

VictoriaMetrics (Prometheus-compatible TSDB) on vm-01. Receives metrics
two ways: pushed by Alloy (every managed host) and pulled at `:9100`
from the Tanium cluster.

## What it does

- Downloads the upstream binary (`victoria-metrics-prod`) from the
  GitHub releases pinned by `victoriametrics_version`.
- Renders the systemd unit + scrape config (`prometheus.yml.j2`).
- Sets `-retentionPeriod=1y` (one year of metric history; coupled with
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

`deploy_monitoring.yml`'s play 3 (`Configure VictoriaMetrics`).
