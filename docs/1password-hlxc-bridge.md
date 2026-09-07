# 1Password-over-hlxc bridge

Gives `hermes-gw-01` (and the interactive `hermes` CLI session inside it)
on-demand access to **arbitrary** 1Password Personal vault items, gated by
a physical approval prompt (Touch ID / security key) on the personal
MacBook **every single time** — with no 1Password service-account token,
no vault password, and no decrypted secret ever written to the box's disk.

Designed 2026-09-06 and verified end-to-end the same day (see
"Verification" below).

## Why this shape

The end goal was 1Password as the single secrets source for the gateway.
1Password **Connect / Credential Broker are Business-tier** features and
the account in use is a Personal plan, so the usual server-side
integration path is unavailable. Anything that *would* let the box read
secrets unattended (a service-account token, a stored vault password)
also violates the hard requirement: nothing secret at rest on
hermes-gw-01. The only remaining gate that satisfies "physical approval
every time" is the real `op` CLI running on the Mac, where 1Password
Desktop pops its native approval dialog. So the design moves the *call*
to the Mac instead of the *credential* to the box.

## Architecture

```
hermes-gw-01                                   personal MacBook
───────────────────────────────                ──────────────────────────────
hermes user runs `op read ...`                 ~/.zshrc: hlxc() shell function
        │                                              │
        ▼                                              │ starts if not running:
~/.local/bin/op  (op_shim.py)                        ~/bin/op-broker.py
        │  connects to Unix socket                     │ listens on ~/.op-broker.sock
        ▼                                              ▼
/run/hermes-op-broker.sock  ◄──── SSH -R reverse ────  ssh -t ... hermes-gw-01
   (srw-rw-rw-, exists only    forward (per hlxc
    while the hlxc session     connection)
    is up)
                                                       broker runs the REAL
                                                       /opt/homebrew/bin/op with
                                                       the shim's argv → 1Password
                                                       Desktop pops Touch ID /
                                                       security-key dialog →
                                                       result returns as JSON
```

Three components:

1. **`~/bin/op-broker.py` (Mac)** — a small daemon on a local Unix socket
   (`~/.op-broker.sock`, mode 0600). For each JSON request
   `{"args": [...]}` it runs the real local `op` CLI with those args and
   returns `{"returncode","stdout","stderr"}`. Because `op` runs natively
   on the Mac, **this is what triggers the per-request Touch ID dialog**.
   Logs to `~/.op-broker.log` — request argv (item *references* like
   `op://Personal/Discord/password`, never values), return code,
   `stdout_len` (a byte count, not content), and truncated stderr.

2. **`roles/hermes_gateway/files/op_shim.py` → `/home/hermes/.local/bin/op`
   (hermes-gw-01)** — a drop-in `op` replacement. Connects to
   `/run/hermes-op-broker.sock` (overridable via `OP_BROKER_SOCK`),
   sends `{"args": sys.argv[1:]}`, prints the broker's stdout/stderr and
   exits with its return code — indistinguishable from a local `op` for
   any caller. 90-second timeout (human approval takes real time).
   Fails immediately with a clear message if the socket doesn't exist,
   i.e. whenever no hlxc session is currently forwarding it. Deployed by
   the `Deploy 1Password op Shim (hlxc bridge)` task in the
   `hermes_gateway` role, so it survives re-provisioning. It shadows
   nothing — the real `op` is not installed on the box.

3. **`~/.zshrc` `hlxc()` function (Mac)** — replaces the old
   `hlxc` alias. Before connecting it (a) checks whether the broker
   socket is alive with a quick `python3` Unix-socket connect, (b) if
   not, removes the stale socket file and starts
   `python3 ~/bin/op-broker.py` in the background, then (c) opens the
   SSH session with `-o ExitOnForwardFailure=yes
   -R /run/hermes-op-broker.sock:~/.op-broker.sock` before attaching the
   tmux session (`TERM=xterm-256color su - hermes -c "tmux new-session
   -A -s hermes-main hermes"`). The reverse socket only exists while
   that SSH connection is alive, so the bridge is physically open only
   while the user is attached.

The `.zshrc`/`op-broker.py` pieces are Mac-local shell config/tooling,
deliberately not part of the ansible repo.

### sshd prerequisite

The reverse-forwarded socket is created by **root's** sshd process, with
mode `0177` (root-only) by default — the unprivileged `hermes` user's
shim would get EACCES. `StreamLocalBindMask 0111` makes it land
`srw-rw-rw-`. On hermes-gw-01 this lives in
`/etc/ssh/sshd_config.d/hermes-op-forward.conf`, written by the
`Configure sshd for the hlxc reverse-socket forward` task (Ubuntu 22.04
sshd reads `Include /etc/ssh/sshd_config.d/*.conf`, and per-connection
sshd means new connections pick it up with no reload). No other sshd
grant is needed: hlxc connects as root, `AllowStreamLocalForwarding`
defaults to yes, and `GatewayPorts` is TCP-only (irrelevant to Unix
sockets).

## What is intentionally NOT here

- **No unattended access.** No hlxc session → no socket → every `op`
  call from the box fails fast. Secrets are reachable only while the
  user is on the box, and every read still needs a physical approval on
  the Mac.
- **Nothing secret on the box.** No vault password, no service-account
  token, no decrypted secret is ever written to hermes-gw-01's disk. The
  only artifact is the socket file itself, in tmpfs `/run`, alive only
  during the SSH session. (The bot's own runtime secrets still come
  from the ansible vault via `env.j2` — see "Open decision" below.)
- **No new vault.** Uses the existing Personal vault, arbitrary item
  names — the shim forwards whatever args it's given rather than a
  baked-in item list.

## Verification (2026-09-06)

Verified against the *real* `hlxc` function (sourced from `~/.zshrc` in a
fresh interactive zsh; only the final interactive ssh command was
intercepted to run non-interactive checks), with the broker initially
down and its socket file stale:

- The function cleaned up the stale socket, started the broker, and
  invoked ssh with exactly:
  `-t -o ExitOnForwardFailure=yes -R /run/hermes-op-broker.sock:~/.op-broker.sock hermes-gw-01 "TERM=xterm-256color su - hermes -c 'tmux new-session -A -s hermes-main hermes'"`
- The remote socket landed `srw-rw-rw- root root /run/hermes-op-broker.sock`
  (fresh connection reading the drop-in — proving the codified sshd
  config, not the old hand-edit, is what's in effect).
- `su - hermes -c 'op read "op://Personal/Discord/password" | wc -c'`
  returned **21** — byte-identical to running the same `op read | wc -c`
  directly on the Mac, proving the full round trip: remote shim →
  reverse tunnel → Mac broker → real Touch-ID-gated `op`.
- Re-run check: with the broker alive, the liveness probe connects and
  a second `hlxc` reuses the broker without spawning a duplicate.
- Broker log audit: only argv references, rc, `stdout_len`, truncated
  stderr — secret values never logged.
- `hermes-gateway.service` untouched throughout (checked `active`
  before and after).

## Open decision — migrating the bot's own runtime secrets

The stated end goal is 1Password as the single source of truth, but the
gateway's *runtime* secrets (Discord bot token, HASS token, etc.) are
still sourced from the ansible vault (`vault_hermes_gw_*` in
`ansible/inventory/group_vars/all.yml`) and rendered into the service's
`.env` at deploy time. That is a **deliberately separate phase** this
design does not change:

- The systemd service runs unattended; the hlxc bridge is
  approval-per-read and only alive while a session is attached — the
  bridge *cannot* serve as the service's secret store as-is.
- The same vault vars also feed four other roles (ha_log_shipper,
  adguard_log_shipper, grafana_ack_bot, hermes_gateway), so "retire the
  ansible vault" is a fleet-wide change, not a single-box one.

Candidate paths when this is picked up (each needing a live-service
decision from the user): a periodic approved refresh of `.env` from
1Password during an interactive session; or re-evaluating a Personal-plan
compatible unattended option. **Do not** point the live
`hermes-gateway.service` at the bridge without an explicit decision.