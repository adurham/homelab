# 2026-09-12: DeepSeek-V4.1-Flash swap (retiring deepseek-v4-flash:0731)

## What changed

Ollama released `deepseek-v4.1-flash` on ollama.com (2026-09-10), adding
vision/image input support to the Flash tier. Retired the old
`deepseek-v4-flash:0731` / bare `deepseek-v4-flash` everywhere it was used
for cost-tier ollama-cloud routing, across all three routing-config copies:

- `~/.hermes/config.yaml` (MacBook, personal profile)
- `ansible/roles/hermes_gateway/vars/model_routing.yml` (source of truth)
- `ansible/roles/hermes_gateway/templates/config.yaml.j2` (Discord bot gateway)
- `ansible/roles/hermes_gateway/templates/dashboard_profile_config.yaml.j2`
  (web dashboard profile)

43 local-config value changes, 34 model_routing.yml value changes, plus the
non-`hermes_routing_*`-templated blocks in both Jinja templates
(`fallback_providers`, `agent.reasoning_effort_by_model`,
`auxiliary.exo.*`, and the dormant `model.default` for the
`hermes_gateway_main_provider == 'ollama-cloud'` branch).

## Why (pricing + benchmarks, verified live 2026-09-12)

Per-1M-token pricing (ollama.com/pricing):

| Model | Input | Output | Cached input |
|---|---|---|---|
| deepseek-v4-flash:0731 (old) | $0.22 | $0.66 | — |
| deepseek-v4.1-flash (new) | $0.15 | $0.60 | $0.003 |

Cheaper on every axis. Benchmarks (High-effort mode, from the model's own
ollama.com listing) are mixed but net favorable for the roles this tier
actually does:

- Codeforces Elo: 3289 (old) -> 3471 (new) — beats even deepseek-v4-pro (3348)
- MathArena Apex: 58.6 -> 65.6 — ties/beats Pro (65.3)
- GPQA Diamond: 89.9 -> 90.9 (small win)
- HLE (Humanity's Last Exam): 37.8 -> 36.8 (small loss — the one metric
  where it's not better than the old Flash)

Live smoke test against the real API confirmed: 200 OK, correct answers,
`reasoning_effort` param (low/high/max) accepted and respected.

## Scope decision: Tier A only, Tier B (Pro-tier) held

Got a second opinion (mcp__consult) before touching anything beyond the
straight Flash->Flash swap. Verdict: promoting *any* current
`deepseek-v4-pro:0813` roles down to V4.1-Flash based on this benchmark
table would be reasoning from the wrong proxies:

- Codeforces/MathArena are single-shot algorithmic/math benchmarks, not
  representative of agentic coding roles (repo context, multi-step tool
  use, long-horizon reliability) — SWE-bench/Terminal-Bench/Aider-Polyglot
  would be the right comparison and DeepSeek didn't publish those for V4.1.
- Benchmark numbers are at "High" reasoning effort — reasoning tokens are
  billed output tokens, so the sticker-price gap can evaporate if V4.1-Flash
  needs more reasoning tokens to hit those scores. Not verified either way.
- Two of the roles in my draft Tier-B proposal (`repo-architect`,
  `database-specialist`) contradicted the existing role taxonomy on this
  same config (every other `*-architect` role stays on Pro; database
  schema judgment leans on the same breadth axis — GPQA/HLE — where V4.1
  isn't a clear win).
- Downgrading `production-validator`/`test-architect` alongside `sr-coder`
  would put the same model family on both the producer and its own gate —
  exactly the correlated-blind-spot problem `kimi-k2.7-code` was
  deliberately kept on `reviewer`/security roles to avoid.

Decision: **no Pro-tier role or aux task moved.** `deepseek-v4-pro:0813`
stays pinned everywhere it already was (pm, consultant, planner,
architecture family, compression, memory_extraction, triage_specifier,
goal_judge, kanban_decomposer, delegation_router, approval,
moa_aggregator, background_review, sr-coder, production-validator,
test-architect, database-specialist, repo-architect, etc.).

If a future session wants to revisit Tier B: build a small (10-20 item)
real-transcript regression set per candidate role, run both models on it,
and route by consequence (cheap-to-verify / high-volume roles are safer
downgrade candidates than silent-failure or gating roles) — not by
matching benchmark categories to role names.

## What did NOT change

- `deepseek-ai/DeepSeek-V4-Flash-0731` — the exo cluster's own local MLX
  checkpoint id (self-hosted weights on the Mac Studios, unrelated to
  Ollama Cloud). Appears in `agent.reasoning_effort_by_model` and is a
  completely different deployment; left untouched.
- Every `deepseek-v4-pro:0813` pin (see above).
- `gemma4:31b`, `glm-5.3-flash`, `kimi-k2.7-code` tiers — no case to move,
  out of scope for this swap.

## Verification performed before considering this "done"

1. Local `~/.hermes/config.yaml` re-parses cleanly (`yaml.safe_load`),
   zero remaining `deepseek-v4-flash`/`deepseek-v4-flash:0731` literals
   outside the untouched exo checkpoint id.
2. `ansible/roles/hermes_gateway/vars/model_routing.yml` re-parses cleanly
   via `ruamel.yaml` round-trip; `hermes_routing_ollama_cloud_models`
   catalog gained a `deepseek-v4.1-flash: {context_length: 1048576}` entry.
3. `python3 scripts/hermes_config_sync.py --check` — exit 0, zero drift
   between local config and the ansible vars file.
4. Both Jinja templates parse (`jinja2.Environment().parse()`) with no
   syntax errors.
5. Both Jinja templates were **fully rendered** with real `defaults/main.yml`
   + `vars/model_routing.yml` values (StrictUndefined, so any missing var
   would hard-fail) and the rendered output re-parsed as YAML successfully;
   spot-checked `fallback_providers[0].model` and
   `delegation.model_by_role.coder.model` both resolve to
   `deepseek-v4.1-flash` in both renders.
6. Live API smoke test: `curl` against `https://ollama.com/v1/chat/completions`
   with `model: deepseek-v4.1-flash` returned 200 with a correct answer,
   confirming the model id is live and callable before wiring it into config.

## Not yet done (needs explicit go-ahead per standing trust rules)

- `ansible-playbook deploy_hermes_gateway.yml --limit hermes_gateway` —
  pushes this to the live hermes-gw-01 box and restarts
  `hermes-gateway.service` (Discord bot) + `hermes-serve.service`
  (dashboard). Not run yet; this is a live-service relaunch, same trust
  rule as exo cluster relaunches — needs its own explicit yes even though
  the config change itself is approved/committed.
- Current MacBook interactive session will not pick up the local config
  change until `/reset` or a new session — delegation config is loaded at
  session start, not read live.
- No dated checkpoint tag exists yet for `deepseek-v4.1-flash` on
  ollama.com (only the floating alias, as of this writing) — re-pin to a
  dated tag once Ollama publishes one, same as the old `:0731` pin, so an
  unannounced upstream checkpoint swap can't silently change behavior.
