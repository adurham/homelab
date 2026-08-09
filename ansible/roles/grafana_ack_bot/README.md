# roles/grafana_ack_bot

Deploys a standalone Discord reaction-based ack/silence bot for Grafana
alerts to `hermes-gw-01` (systemd service `grafana-ack-bot`). Receives
Grafana alertmanager webhook POSTs, posts formatted alerts to
`#infra-alerts` with reaction options, and turns reactions into real
Grafana Alertmanager actions.

Deliberately a SEPARATE process from `hermes-agent`/the main gateway,
not an extension of hermes-agent's own Discord adapter — Discord routes
message-component interactions (buttons) via ONE global per-application
"Interactions Endpoint URL" setting, which hermes-agent already owns for
its own approval-button UI. Pointing that at a new receiver would
silently redirect ALL of Hermes's interactions here and break existing
features. Reactions carry no such conflict (plain Gateway events any
connected session for the bot token receives), so a fully separate
process on the SAME existing Hermes Discord bot token is safe and
additive — no new Discord application. Full design rationale in the
module docstring at the top of `files/service.py`.

## What it does

- Installs a dedicated Python venv (`/opt/grafana-ack-bot-venv`,
  `discord.py` + `aiohttp`) and deploys `files/service.py` to
  `/opt/grafana-ack-bot/`.
- Renders the env file (`templates/grafana-ack-bot.env.j2`) with the
  Discord bot token (reused from `vault_hermes_gw_discord_bot_token`),
  the `#infra-alerts` webhook URL, and a scoped Grafana service-account
  token.
- Installs and enables the `grafana-ack-bot.service` systemd unit.
- Default-deny iptables on the receiver port (tcp/8990): only graf-01
  and loopback allowed in, mirroring `roles/hermes_gateway`'s pattern
  for its own exposed ports.

## Two reaction outcomes (deliberately different operations)

Modeled on ScienceLogic EM7's ack semantics — ack suppresses NEW
notifications but the alert stays live/updating until it actually
resolves, not until a fixed timer. Grafana has no native ack primitive
(only time-boxed, deletable Alertmanager silences), so this is the
closest honest approximation achievable on its real API surface:

- **👀 (ack)** — creates a 30-day-ceiling Alertmanager silence with
  EXACT matchers on every current label (so e.g. a severity change is a
  genuinely new alert instance that is NOT covered by the old ack and
  notifies again), plus a permanent Grafana annotation
  (`POST /api/annotations`, tagged `ack`) for the record. A background
  watcher polls Grafana's active-alerts API every 30s; the moment the
  specific alert instance is no longer active, it deletes the silence
  EARLY and posts a synthesized "Resolved" message to Discord — because
  Grafana's own resolved-notification would otherwise be swallowed by
  the same silence suppressing the firing notifications. Watcher gives
  up (leaving the silence to ride out its 30-day ceiling) after 7 days
  without seeing resolution.
- **1️⃣ / 4️⃣ / 📅 (silence)** — plain fixed-duration (1h/4h/24h)
  Alertmanager silence. No watcher, no synthesized resolved message —
  "stop telling me for exactly N hours, I don't need tracking."

Both scoped per-alert-instance (alertname + every label Grafana
attached), not per-rule — acking/silencing one down host never affects
siblings the same rule could fire on.

Reaction-add calls are serialized through a single process-wide lock
with 429 retry using Discord's own `retry_after` — a burst of several
alerts firing together (e.g. 6 hosts down at once) needs dozens of
near-simultaneous reaction-add calls, which blows through Discord's
per-channel rate-limit bucket if unserialized; verified live that a
6-alert burst now lands all 4 reactions on every message.

## Key variables / vault-sourced secrets

All in `ansible/inventory/group_vars/all.yml`:

- `vault_hermes_gw_discord_bot_token` — reused from `roles/hermes_gateway`.
- `discord_infra_alerts_webhook_url` — same webhook the
  `discord_infra_alerts` Grafana contact point posts to (see
  `roles/grafana`); the ack bot both posts through it and edits its own
  messages via the webhook's own edit-message endpoint (required —
  webhook-authored messages 403 on the normal bot message-edit API).
- `discord_infra_alerts_channel_id` — numeric channel ID, not a secret.
- `grafana_ack_bot_sa_token` — Grafana service-account token (Editor
  role, `sa-1-discord-ack-bot`), created manually via Grafana's API for
  this bot's Silence/Annotation calls. Grafana's own `admin_password` in
  `grafana.ini` only applies on first-ever boot — if this token or the
  Grafana admin login ever need regenerating, reset via
  `grafana-cli admin reset-admin-password` first if `grafana_admin_password`
  no longer authenticates (the deployed account can drift from vault).
- `discord_owner_user_id` — the only Discord user ID allowed to
  ack/silence (`ALLOWED_USER_IDS` in the env file).

## Where it's invoked

`deploy_grafana_ack_bot.yml` against the `hermes_gateway` inventory
group (same host as the main Hermes gateway, different systemd unit).

## Grafana-side wiring

The `discord_infra_alerts` contact point in `roles/grafana` is a plain
`webhook` type (NOT `type: discord`) pointed at
`http://172.16.0.50:8990/grafana-webhook` — this bot receives the raw
alertmanager payload and does the Discord posting itself, rather than
Grafana's native Discord integration posting directly (which has no
ack/silence capability of its own).

## Known gaps

- Pending-ack/silence state (`_pending` dict) is in-memory only, lost on
  service restart. A message posted before a restart can't be
  acked/silenced via reaction afterward — still visible/actionable
  directly in Grafana. No persistence layer added yet (kept this a
  single dependency-free file); revisit if this gap proves painful.
