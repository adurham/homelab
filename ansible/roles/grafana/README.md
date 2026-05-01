# roles/grafana

Installs Grafana on graf-01 with provisioned datasources, dashboards,
contact points, notification policies, and alert rules. Builds the
grafana-image-renderer plugin from source (Go required) for PDF/PNG
export.

## What it does

- apt-installs `grafana` from the upstream Grafana repo.
- Builds `grafana-image-renderer` v{{ grafana_image_renderer_version }}
  from source using Go {{ go_version }}. Source build because the
  prebuilt binary expects a glibc that's newer than the LXC's.
- Provisions datasources (`datasource.yml.j2` → VictoriaMetrics + Loki).
- Provisions dashboards via `templates/dashboards.yml.j2` + JSON files
  in `files/`.
- Provisions alerting (rules, contact points, notification policies)
  via the three `alerting_*.yml.j2` templates.
- Wires Authentik OIDC SSO via `[auth.generic_oauth]` in grafana.ini.

## Key variables (`defaults/main.yml`)

- `go_version`, `grafana_image_renderer_version` — Renovate-tracked.

## Vault-sourced secrets

- `grafana_client_secret`, `grafana_admin_password` — OIDC + admin login.
- `grafana_alert_webhook_id` — Home Assistant webhook for iOS push.
- `healthchecks_dms_ping_url` — dead-man's-switch URL. Optional;
  the DMS pipeline (rule + contact point + policy) only renders when
  this is set.

## Alerts

See `templates/alerting_rules.yml.j2`. 18 rules covering hosts down,
disk full, log-based events (OOM, postgres FATAL, SSH brute-force,
postfix relay), cert expiry runway, pve replication failures, pve
quorum loss, and the always-firing dead-man's-switch.

## Where it's invoked

`deploy_monitoring.yml`'s play 4 (`Configure Grafana`).
