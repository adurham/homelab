# roles/hermes_gateway

Configures `hermes-gw-01` (CT 113) — the bot/agent gateway that
exposes Hermes' API + Discord adapter to the homelab. The host LXC
itself is created by `roles/hermes_gateway_host`; this role only
handles the application layer.

## What it does

- Clones / pulls the `hermes-agent` repo at the pinned ref.
- Writes the runtime env from `templates/env.j2` (Discord token,
  Anthropic creds, etc. — all sourced from vault).
- Writes `config.yaml` from `templates/config.yaml.j2` (Hermes runtime
  config — model providers, toolsets, etc.).
- Installs the api_server + discord adapter systemd units.
- `tailscale serve` over the LXC's own Tailscale identity to expose
  `https://hermes-gw-01.<tailnet>.ts.net` (Tailnet-only). api_server
  itself listens on 127.0.0.1:8642 — Tailscale handles the TLS + L3.
- Defense-in-depth iptables INPUT rules on tcp/8642:
  - Allow loopback, ESTABLISHED/RELATED, Tailnet CGNAT (100.64/10),
    `ip_tailscale_gw` (covers the subnet-router SNAT case), and the
    LXC's own IP.
  - DROP everything else.
  Rules are dead today (api_server is loopback-only) but stay as
  belt-and-braces in case the bind ever moves.

## Key variables

Most secrets live in `ansible/inventory/group_vars/all.yml` as
`vault_hermes_gw_*` entries (Discord token, Anthropic creds, Gemini
OAuth, HASS token, OAuth tokens, internal api_server key, per-principal
adapter keys for audit logging).

## Where it's invoked

`deploy_hermes_gateway.yml` after `hermes_gateway_host` has
created/started the CT.
