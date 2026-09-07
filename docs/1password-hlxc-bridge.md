# 1Password-over-hlxc bridge

Gives `hermes-gw-01` (and the interactive `hermes` CLI session inside it)
on-demand access to **arbitrary** 1Password Personal vault items, gated by
a physical approval prompt (Touch ID / security key) on the personal
MacBook **every single time** — with no 1Password service-account token,
no vault password, and no decrypted secret ever written to the box's disk.

Designed 2026-09-06 and verified end-to-end the same day (see
"Verification" below).

A second, unrelated capability — a clipboard-image bridge — was added
2026-09-07 on top of the same broker process and socket. See "Layer 2:
clipboard bridge" below. It has materially different security properties
than the 1Password path documented in this section; read that section's
"Security posture" before assuming the two share the same guarantees.

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

## Layer 2: clipboard bridge

Added 2026-09-07 on top of the exact same broker process, socket, and
reverse-tunnel forward described above — not a new bridge, a second
request type carried over the existing one.

### Why it exists

Ctrl+V/Alt+V image paste needed to work for a `hermes` CLI session running
on `hermes-gw-01`, but the image the user wants to paste lives on the
MacBook's clipboard, not the headless box's (which has no display server
or clipboard daemon at all). An earlier fix used kitty's `kitten
clipboard` (OSC 5522 over the tty) to pull the image directly over the
terminal protocol — that works for a plain SSH session, but the real
day-to-day access path (the `hlxc` alias) always lands inside a tmux
session, and tmux's server drops a pane's unwrapped OSC 5522 request
outright. Inside tmux the OSC-5522 route silently does nothing. The
clipboard bridge exists to reach the Mac's clipboard through a channel
tmux cannot see: the same reverse-forwarded Unix socket the 1Password
bridge already uses, which carries SSH-channel traffic, not tty bytes.

### How it works

Same architecture diagram as above, same socket, same daemon process
(`~/bin/op-broker.py`) — no separate broker, no separate tunnel. The
broker now dispatches on a `"type"` field in the JSON request:

- No `"type"` key → the original 1Password `op`-forwarding behavior,
  unchanged and byte-compatible.
- `{"type": "clipboard_read"}` → the broker reads the Mac's clipboard
  locally (`pngpaste`, falling back to `osascript`) and returns the image
  as base64-encoded PNG: `{"returncode": 0, "png_b64": "..."}`.
- `{"type": "clipboard_has_image"}` → a cheap existence check without
  transferring image bytes: `{"returncode": 0, "has_image": true|false}`.

Response codes carry meaning the remote client (`hermes_cli/clipboard.py`
in the hermes-agent fork) depends on: `rc=0` success, `rc=1` a definitive
"no image on the clipboard", `rc=2` an internal error or the size cap
being hit (treated as "bridge unavailable, fall back to another
clipboard backend"), and `rc=3` "refused — the Mac's screen is locked."
The broker logs request type, return code, and byte lengths only — never
clipboard content or base64 payloads, matching the existing `op` logging
discipline.

### Security posture: clipboard bridge (Layer 2)

This section is deliberately blunt. The clipboard path reduces the
security guarantee that the 1Password path above provides, and that
reduction was a conscious tradeoff, not an oversight.

- **Not Touch-ID-gated.** The 1Password `op` reads documented above are
  safe specifically because the *real* `op` CLI runs natively on the Mac
  and 1Password Desktop pops a physical Touch ID / security-key prompt on
  every single call — there is no way to exfiltrate a vault item through
  this bridge without the user's live physical approval. Clipboard reads
  do **not** go through any such gate. Any process that can reach the
  broker socket while an hlxc session is live can request the Mac's
  current clipboard contents and get them back, no prompt, no approval,
  no user awareness that a read happened.
- **The only mitigations are narrow and partial, not a security
  boundary.** Two checks run broker-side before a clipboard read is
  served:
  1. The broker refuses the request outright (`returncode=3`) if the
     Mac's screen is locked (`ScreenSaverEngine` running) — a read
     attempted while the user has stepped away and locked the machine
     gets nothing.
  2. A 24 MB cap on the clipboard payload bounds how much data a single
     read can move.
  Neither of these makes the clipboard read safe in the way the Touch-ID
  gate makes the `op` read safe — they narrow the exposure window and cap
  the blast radius, nothing more. While the Mac is unlocked and an hlxc
  session is live, clipboard contents are readable with no per-read
  consent of any kind.
- **The forwarded socket is world-accessible on hermes-gw-01, and any
  local user on that box can reach it.** The reverse-forwarded socket is
  created by root's sshd, and the `StreamLocalBindMask 0111` sshd
  drop-in (`/etc/ssh/sshd_config.d/hermes-op-forward.conf`, described
  under "sshd prerequisite" above) makes it land `srw-rw-rw-` — world
  read/write, not scoped to the `hermes` user. That mask exists because
  the unprivileged `hermes` user (who is not the SSH-login user) has to
  be able to reach a socket that root's sshd created on behalf of the
  SSH-login session; there is no narrower mask that still lets `hermes`
  connect. The practical consequence: **any local user on hermes-gw-01
  can connect to that socket and read the Mac's clipboard for as long as
  an hlxc session is live** — this is not hypothetical or theoretical,
  it follows directly from the socket's permission bits. This was a
  consciously accepted tradeoff at design time, mitigated by the
  broker-side screen-lock refusal and size cap described above rather
  than by tightening the socket mask (tightening the mask would break
  the `hermes` user's own legitimate access, which is the entire point
  of the bridge).
- **Net assessment.** The clipboard bridge trades a real, unaudited
  read-access exposure (bounded by "hlxc session live" + "screen
  unlocked" + 24 MB) for tmux compatibility. It is materially weaker than
  the 1Password path on this page, which has no such exposure because
  every read requires the user's own physical Touch ID / security-key
  approval at the moment of the read. Anyone extending this bridge to
  carry additional request types should assume the same
  no-per-read-consent, any-local-user-on-the-box exposure applies unless
  a new type adds its own gate.
