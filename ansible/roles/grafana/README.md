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
  Note: `admin_password` in grafana.ini only sets the account password
  on Grafana's very first boot — if the deployed account ever drifts
  from vault (e.g. changed once via the UI), config redeploys alone
  won't fix it; reset via `grafana-cli admin reset-admin-password` on
  graf-01 first.
- `grafana_alert_webhook_id` — Home Assistant webhook for iOS push.
- `healthchecks_dms_ping_url` — dead-man's-switch URL. Optional;
  the DMS pipeline (rule + contact point + policy) only renders when
  this is set.
- `discord_infra_alerts_webhook_url` — Discord webhook for `#infra-alerts`
  (see `roles/grafana_ack_bot`, which owns the actual posting/ack flow).
- `alert_email_to` — email fallback contact point address.

## Alerts

See `templates/alerting_rules.yml.j2`. 21 rules covering hosts down,
disk full, log-based events (OOM, postgres FATAL, SSH brute-force,
postfix relay), cert expiry runway, pve replication failures, pve
quorum loss, smart_vent_controller heartbeat staleness, Tati's WiFi
presence tracker staleness, and the always-firing dead-man's-switch.

## Notification routing

Every alert fans out in parallel (each `continue: true`) to:

1. **Home Assistant webhook** → `notify.mobile_app_adams_iphone_16` push
   (critical bypasses DND if any alert in the batch is `severity:
   critical`).
2. **Discord** (`discord_infra_alerts` contact point) — a plain
   `webhook` type (NOT `type: discord`) pointed at
   `roles/grafana_ack_bot`'s receiver on hermes-gw-01. That service does
   the actual Discord posting AND adds reaction-based ack/silence —
   Grafana's native Discord integration has no ack capability of its
   own, hence the indirection. See `roles/grafana_ack_bot/README.md`
   for the full ack/silence design.
3. **Email** → mail-01 → iCloud SMTP relay, independent of HA being up.
4. **Dead-man's-switch** (if `healthchecks_dms_ping_url` set) — the
   always-firing `dead_mans_switch` rule pings healthchecks.io every 5m;
   catches the case where Grafana/network/mail-01 are all down at once
   and the other three contact points can't deliver.

## Where it's invoked

`deploy_monitoring.yml`'s play 4 (`Configure Grafana`).
