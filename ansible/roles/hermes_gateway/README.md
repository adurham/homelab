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
- Writes `/home/hermes/.tmux.conf` from `templates/tmux.conf.j2` — sets
  `default-terminal tmux-256color` + RGB `terminal-overrides` so the
  interactive `hlxc` SSH+tmux session renders 24-bit color correctly
  (the CT lacks kitty terminfo, so `hlxc` forces
  `TERM=xterm-256color`; without this file tmux falls back to its
  bundled `screen` terminfo, which has no truecolor capability, and
  hermes-agent's RGB banner/gradients render washed-out/blocky). A
  live `hermes-main` tmux session must have its server killed
  (`tmux kill-server`, as the `hermes` user) for a fresh render to
  pick up a first-time deploy of this file — not automated, since
  killing a live interactive session unasked breaks trust.
- Deploys the 1Password `op` shim (`files/op_shim.py` →
  `/home/hermes/.local/bin/op`) and the sshd drop-in
  (`/etc/ssh/sshd_config.d/hermes-op-forward.conf`,
  `StreamLocalBindMask 0111`) backing the **1Password-over-hlxc
  bridge**: while a `hlxc` session from the personal MacBook is
  attached, the `hermes` user's `op` calls forward over a reverse
  Unix-socket tunnel to the Touch-ID-gated real `op` on the Mac —
  arbitrary Personal-vault items, physical approval per read, nothing
  secret ever on this box's disk. Full design + verification:
  `docs/1password-hlxc-bridge.md`.
- Installs the **`kitten` standalone binary** (kitty v0.46.2,
  linux-amd64, sha256-pinned) at `/home/hermes/.local/bin/kitten` so
  hermes-agent's Ctrl+V/Alt+V clipboard-image paste works from inside
  the `hlxc` session: the headless CT has no display server or clipboard
  daemon, so the only reachable clipboard is the LOCAL kitty terminal's,
  and `kitten clipboard -g` reads it over the OSC 5522 tty protocol
  (auto-wrapped through tmux passthrough). Requires
  `read-clipboard`/`read-primary` in the local kitty.conf's
  `clipboard_control` (already set on the personal MacBook) for silent
  reads — kitty's default config prompts per read instead.
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

## Model-routing config drift (MacBook vs this gateway)

The MacBook's local `~/.hermes/config.yaml` and this gateway's
`templates/config.yaml.j2` both carry the same `delegation.model_by_role`
(62 delegate_task personas), `delegation.by_provider`, and
`auxiliary.anthropic`/`auxiliary.ollama-cloud` task-routing tables —
independently maintained, and they've drifted out of sync via manual
copy-paste more than once (2026-09-04/07/08/12), including one real bug
(`delegation.by_provider.anthropic` silently pinning `claude-sonnet-5` as
PRIMARY on one copy after the other had already been fixed).

`vars/model_routing.yml` is the single written source of truth for that
routing data. To re-tier a role or auxiliary task:

1. Edit the relevant entry in `vars/model_routing.yml`.
2. Manually mirror the same edit into `templates/config.yaml.j2`'s
   `delegation.model_by_role` / `delegation.by_provider` / `auxiliary.*`
   blocks — **the template does not yet render from the vars file** (see
   "Known gaps" below), so today this is still two hand-edits, not one.
3. `ansible-playbook deploy_hermes_gateway.yml --limit hermes_gateway` to
   push it to hermes-gw-01.
4. From the repo root: `.venv/bin/python3 scripts/hermes_config_sync.py
   --apply` to mirror the same values into the MacBook's local
   `~/.hermes/config.yaml` (dry-run without `--apply`; `--check` exits
   non-zero on drift, for scripting). Requires `ruamel.yaml` in `.venv`
   (`uv pip install --python .venv/bin/python3 ruamel.yaml` if missing —
   it's listed in `scripts/requirements.txt` but that file is not
   auto-installed by anything yet).

**Known gaps (as of 2026-09-12, not yet fixed):**

- `templates/config.yaml.j2` hardcodes this data rather than rendering it
  from `vars/model_routing.yml` — step 2 above is a manual mirror, which
  is exactly the failure mode this file exists to prevent. Rewiring the
  template to render from the vars file (e.g. via `to_nice_yaml`) is the
  proper fix; deferred because it touches a live, working prod template
  and needs a zero-behavior-diff render proof before deploying.
- `templates/dashboard_profile_config.yaml.j2` (the separate profile
  behind `hermes.chi.lab.amd-e.com`, see "What it does" above) has its
  **own third hardcoded copy** of this same routing data that neither the
  2026-09-12 cost-review re-tier nor this fix touched. It is still on
  pre-re-tier values (e.g. `glm-5.3` instead of the current tiers) and
  still has the `by_provider.anthropic` primary-pinning bug, live on
  `hermes-gateway-dashboard.service` + `hermes-serve.service`.

## Key variables

Most secrets live in `ansible/inventory/group_vars/all.yml` as
`vault_hermes_gw_*` entries (Discord token, Anthropic OAuth token,
Ollama Cloud API key, Gemini OAuth, HASS token, internal api_server
key, per-principal adapter keys for audit logging, the Hermes API M2M
client_secret, and the Hermes Dashboard OIDC client_id).

## Where it's invoked

`deploy_hermes_gateway.yml` after `hermes_gateway_host` has
created/started the CT.
