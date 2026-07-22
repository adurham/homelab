# roles/hermes_gateway

Configures `hermes-gw-01` (CT 113) — the bot/agent gateway that
exposes Hermes' API + Discord adapter to the homelab, plus (since
2026-07-22) a persistent `hermes serve` backend for remote GUI/CLI
access. The host LXC itself is created by `roles/hermes_gateway_host`;
this role only handles the application layer.

## What it does

- Clones / pulls the `hermes-agent` repo at the pinned ref.
- Writes the runtime env from `templates/env.j2` (Discord token,
  Anthropic OAuth token, Ollama Cloud API key, etc. — all sourced from
  vault. Credentials for all three main-model providers are always
  written, regardless of which one is active — see "Switching the main
  model provider" below).
- Writes `config.yaml` from `templates/config.yaml.j2` (Hermes runtime
  config — model providers, toolsets, etc.).
- Installs the api_server + discord adapter systemd units
  (`hermes-gateway.service`) and the persistent remote-backend unit
  (`hermes-serve.service`, `hermes serve --host 0.0.0.0 --port 9119`).
- `tailscale serve` over the LXC's own Tailscale identity to expose
  `https://hermes-gw-01.<tailnet>.ts.net` (Tailnet-only) for api_server.
- lb-01's nginx additionally fronts both services for the homelab LAN,
  gated by Authentik — see `roles/authentik_provider/tasks/hermes.yml`:
  - `https://hermes.chi.lab.amd-e.com` → hermes-serve (native OIDC
    "Sign in with Authentik" login, TLS+WS passthrough only).
  - `https://hermes-api.chi.lab.amd-e.com` → api_server (nginx
    `auth_request` forward-auth against an Authentik M2M
    client_credentials JWT, then re-attached with api_server's own
    `API_SERVER_KEY` server-side — two independent gates).
- Defense-in-depth iptables INPUT rules on tcp/8642 (api_server) and
  tcp/9119 (hermes serve): allow loopback, ESTABLISHED/RELATED, Tailnet
  CGNAT (100.64/10), `ip_tailscale_gw`, lb-01, and the LXC's own IP;
  DROP everything else. **Any new ACCEPT rule added to these chains
  must use `action: insert`** (default `state: present` only appends,
  and appending after an existing DROP means the new rule never
  matches — bit us once during the initial 2026-07-22 deploy).

## Switching the main model provider

`hermes_gateway_main_provider` (defaults/main.yml) selects the
gateway's primary reasoning-thread provider: `exo` (default — local Mac
Studio cluster, free/private but requires the cluster to be reachable),
`anthropic` (Claude via the CLAUDE_CODE_OAUTH_TOKEN already deployed),
or `ollama-cloud` (cloud-hosted open models via OLLAMA_API_KEY). All
three providers' credentials and `providers:` blocks are always
rendered into config.yaml/.env regardless of the active selection, so
switching is just:

```
ansible-playbook deploy_hermes_gateway.yml --limit hermes_gateway \
  -e hermes_gateway_main_provider=anthropic
```

(or edit the default in `defaults/main.yml` for a persistent change).
The template change triggers the `Restart Hermes Gateway` and
`Restart Hermes Serve` handlers automatically — no manual SSH needed.
`delegation.*` and `auxiliary.vision` are provider-conditional in the
template: exo gets the cheap-Qwen3.6-subagent routing, anthropic/
ollama-cloud leave `delegation.provider`/`model` empty so subagents
inherit the parent model/credentials instead of being force-routed to
a (possibly-down) exo cluster.

## Key variables

Most secrets live in `ansible/inventory/group_vars/all.yml` as
`vault_hermes_gw_*` entries (Discord token, Anthropic OAuth token,
Ollama Cloud API key, Gemini OAuth, HASS token, internal api_server
key, per-principal adapter keys for audit logging, the Hermes API M2M
client_secret, and the Hermes Dashboard OIDC client_id).

## Where it's invoked

`deploy_hermes_gateway.yml` after `hermes_gateway_host` has
created/started the CT.
