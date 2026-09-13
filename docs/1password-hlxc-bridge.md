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

Also 2026-09-07: the 1Password path itself was extended to support
**multiple concurrent hlxc sessions**, each with its own working bridge.
Originally only the first hlxc window could bind the single fixed remote
socket path; a second window either crashed its whole SSH connection or,
after a partial fix, ran with no 1Password access at all. See "Per-session
socket paths and the tmux-name rationale" under Architecture below for the
new design.

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
        │  connects to $OP_BROKER_SOCK                 │ listens on ~/.op-broker.sock
        ▼                                              ▼ (ThreadingUnixStreamServer)
/run/hermes-op-broker/<tmux-session>.sock  ◄── SSH -R  ssh -t ... hermes-gw-01
   (srw-rw-rw-, one per concurrent hlxc        reverse forward, one per
    session; dir 0755 root:root, file           hlxc connection, all
    mode via StreamLocalBindMask)                forwarding to the SAME
                                                  local socket above
                                                       broker runs the REAL
                                                       /opt/homebrew/bin/op with
                                                       the shim's argv → 1Password
                                                       Desktop pops Touch ID /
                                                       security-key dialog →
                                                       result returns as JSON
```

Three components, one of which now runs a pre-flight step:

1. **`~/bin/op-broker.py` (Mac)** — a small daemon on a local Unix socket
   (`~/.op-broker.sock`, mode 0600), shared by every concurrent hlxc
   session. For each JSON request `{"args": [...]}` it runs the real
   local `op` CLI with those args and returns
   `{"returncode","stdout","stderr"}`. Because `op` runs natively on the
   Mac, **this is what triggers the per-request Touch ID dialog**. Runs
   as `socketserver.ThreadingUnixStreamServer` with `daemon_threads=True`
   (previously a plain single-threaded `UnixStreamServer` — see "Broker
   threading" below for why that mattered and the measured numbers).
   Logs to `~/.op-broker.log` under a `threading.Lock` — request argv
   (item *references* like `op://Personal/Discord/password`, never
   values), return code, `stdout_len` (a byte count, not content), and
   truncated stderr.

2. **`roles/hermes_gateway/files/op_shim.py` → `/home/hermes/.local/bin/op`
   (hermes-gw-01)** — a drop-in `op` replacement. Connects to
   `$OP_BROKER_SOCK` — the per-session remote path hlxc's pre-flight set,
   e.g. `/run/hermes-op-broker/hermes-main.sock` — sends
   `{"args": sys.argv[1:]}`, prints the broker's stdout/stderr and exits
   with its return code — indistinguishable from a local `op` for any
   caller. 90-second timeout (human approval takes real time). If the
   socket is missing, the shim now distinguishes two failure modes with
   different fixes: `OP_BROKER_SOCK` was set but the socket is gone (the
   forwarding SSH connection dropped — reconnect with hlxc) versus
   `OP_BROKER_SOCK` was never set at all (a pane predating this change,
   or a plain `su - hermes` login with no bridge at all — start or attach
   via hlxc instead). Deployed by the `Deploy 1Password op Shim (hlxc
   bridge)` task in the `hermes_gateway` role, so it survives
   re-provisioning. It shadows nothing — the real `op` is not installed
   on the box.

3. **`~/.zshrc` `hlxc()` function (Mac)** — replaces the old
   `hlxc` alias. Before connecting it (a) checks whether the broker is
   alive with a quick `python3` Unix-socket connect to
   `~/.op-broker.sock`, starting `python3 ~/bin/op-broker.py` in the
   background if not, then (b) runs a **pre-flight** over one throwaway
   SSH round-trip (a Python script piped over stdin) that `mkdir -p`s
   `/run/hermes-op-broker` on the box, reaps any socket in that directory
   that is not currently connectable (plus the legacy flat
   `/run/hermes-op-broker.sock` path — see "Stale-socket reaping"
   below), and picks a session name — preferring an existing
   *unattached* tmux session (rescuing an orphaned in-flight
   conversation) over creating a new one, else the first free name from
   `hermes-main`, `hermes-main-2`, ... up to `hermes-main-32`. Then (c) it
   opens the SSH session with `-o ExitOnForwardFailure=yes -R
   /run/hermes-op-broker/<session>.sock:~/.op-broker.sock` — **now
   unconditional for every window**, since distinct *remote* paths cannot
   collide (only two forwards claiming the identical remote path do) —
   before attaching that named tmux session (`TERM=xterm-256color su -
   hermes -c "tmux new-session -A -s <session> hermes"`). The reverse
   socket for a given session only exists while that session's SSH
   connection is alive, so the bridge is physically open only while the
   user is attached to that particular window.

The `.zshrc`/`op-broker.py` pieces are Mac-local shell config/tooling,
deliberately not part of the ansible repo.

### Per-session socket paths and the tmux-name rationale

The remote socket path is `/run/hermes-op-broker/<tmux-session-name>.sock`
— derived from the **tmux session name**, not from anything about the SSH
connection itself (no PID, no random suffix, no connection timestamp).
Keying it off the connection instead looks like the simpler design, and
it is tempting to "simplify" it that way later — don't. The session-name
choice was measured against the box's actual tmux 3.5a, not assumed:

- `tmux new-session -A -e VAR=VAL` sets the session environment variable
  only on the **create** branch. On the **attach** branch (the session
  already exists and `-A` just reattaches it) the `-e` flag is **silently
  ignored** — measured directly: attaching with a changed `-e` left the
  session's stored env at its original value.
- `tmux setenv` does not retroactively rewrite an already-running pane's
  environment either; it only affects processes started after the call.

Put together: any per-*connection* path scheme (random suffix, PID,
connection epoch) would leave a **reattached** session's shell holding an
`OP_BROKER_SOCK` value from its *previous* connection, pointing at a
socket that no longer exists once that old SSH connection is gone — `op`
calls in that pane would fail even though the user just successfully
reattached, and nothing short of restarting the shell would fix it.
Keying the path off the **session name** instead sidesteps the problem by
construction: reattaching a given tmux session always produces the
identical remote path that pane's `OP_BROKER_SOCK` already holds, so
reattach is correct with no special-case fixup code. Verified directly:
created a session, ran `op` successfully, `kill -9`'d the SSH process,
reattached via hlxc, and `op` returned rc=0 in the same original pane
with no shell restart.

### Stale-socket reaping

OpenSSH does **not** unlink an existing file at the remote `-R` bind path
before binding — if a socket file is already there (even a dead one left
by a crashed or `kill -9`'d session), the bind fails with `EADDRINUSE`
and, because `ExitOnForwardFailure=yes` is now on for every window, that
failure kills the entire SSH connection outright rather than degrading to
"no 1Password access." A crashed or forcibly-killed hlxc used to poison
its path this way until someone manually `rm`'d the socket on the box —
this was found as a genuinely stale leftover socket on hermes-gw-01 at
the start of this work, not a hypothetical.

The hlxc pre-flight reaps this class of problem itself: for every socket
file under `/run/hermes-op-broker/` (plus the legacy flat path), it
attempts a real connect and deletes the file if that connect fails,
before any new `-R` forward tries to claim a path. Verified end to end:
after ungracefully killing a tunnel, blindly re-claiming the same path
failed with `remote port forwarding failed for listen path
/run/hermes-op-broker/<session>.sock` (ssh exit 255); running the reaper
first and then re-claiming the same path returned rc=0.

### Broker threading

`~/bin/op-broker.py` was a plain single-threaded
`socketserver.UnixStreamServer` + `serve_forever()` — fine with only one
hlxc session ever existing, but a real serialization bug once multiple
sessions could queue requests through it concurrently: a trivial `op
--version` call was measured blocking **60.044s** behind a single slow,
human-approval-gated request on the same broker, and that first request
then died with a 1Password "authorization timeout" — one slow approval
could starve every other concurrent session, not just delay them.

Fixed by switching to `socketserver.ThreadingUnixStreamServer` with
`daemon_threads=True`, plus a `threading.Lock` around log writes (the log
file isn't otherwise safe for concurrent writers). After the fix, the
same trivial call measured **0.322s** while the slow request was still in
flight — each request now gets its own thread, and 1Password's own Touch
ID approval flow is the only remaining serialization point, at the OS
level, which is expected. Clipboard request handling (see "Layer 2"
below) and the tri-state return-code contract are unchanged by this fix.

### Remote directory persistence

`/run` is tmpfs, so `/run/hermes-op-broker` evaporates on reboot unless
something recreates it. Handled three separate, deliberately redundant
ways:

1. An ansible task in the `hermes_gateway` role creates the directory at
   deploy time.
2. A `systemd-tmpfiles.d` drop-in,
   `/etc/tmpfiles.d/hermes-op-broker.conf`, containing
   `d /run/hermes-op-broker 0755 root root -`, so it comes back on every
   boot without needing a deploy.
3. hlxc's own pre-flight (see "Per-session socket paths" above) does a
   defensive `mkdir -p` regardless, so even a box that somehow lost both
   of the above self-heals on the next connection.

Reboot persistence was proven, not just configured: hermes-gw-01 rebooted
mid-testing (a clean halt initiated from the Proxmox host, unrelated to
this work) and the directory was confirmed present immediately after boot
came back up.

### sshd prerequisite

Each reverse-forwarded socket is created by **root's** sshd process, with
mode `0177` (root-only) by default — the unprivileged `hermes` user's
shim would get EACCES. `StreamLocalBindMask 0111` makes every one of them
land `srw-rw-rw-`. On hermes-gw-01 this lives in
`/etc/ssh/sshd_config.d/hermes-op-forward.conf`, written by the
`Configure sshd for the hlxc reverse-socket forward` task (Ubuntu 22.04
sshd reads `Include /etc/ssh/sshd_config.d/*.conf`, and per-connection
sshd means new connections pick it up with no reload). This setting is
box-wide and needed **no change** for multi-session support — reconfirmed
directly on the box with `sshd -T | grep streamlocalbindmask` → `0111`.
No other sshd grant is needed: hlxc connects as root,
`AllowStreamLocalForwarding` defaults to yes, and `GatewayPorts` is
TCP-only (irrelevant to Unix sockets).

The containing directory, `/run/hermes-op-broker`, is a separate
permission concern from the socket files inside it: it is `0755
root:root` so the unprivileged `hermes` user can *traverse* into it
(needed to reach sockets root's sshd created there) without needing write
access — sshd still creates and owns each socket file itself. See "Remote
directory persistence" above for why the directory survives a reboot.

## What is intentionally NOT here

- **No unattended access.** No hlxc session → no socket for that
  session's path → every `op` call from a pane without a live forward
  fails fast. Secrets are reachable only while the user is attached via
  hlxc, and every read still needs a physical approval on the Mac.
- **Nothing secret on the box.** No vault password, no service-account
  token, no decrypted secret is ever written to hermes-gw-01's disk. The
  only artifacts are the per-session socket files themselves, in tmpfs
  `/run`, each alive only during its own SSH session. (The bot's own
  runtime secrets still come from the ansible vault via `env.j2` — see
  "Open decision" below.)
- **No new vault.** Uses the existing Personal vault, arbitrary item
  names — the shim forwards whatever args it's given rather than a
  baked-in item list.

## Residual limitations (multi-session design)

Honest limitations of the current design, not hidden away:

- **A pane started before this change has no `OP_BROKER_SOCK`.** Any
  session attached before the multi-session hlxc function was deployed,
  or a plain `su - hermes` login done outside hlxc entirely, has no
  `OP_BROKER_SOCK` in its environment and therefore no 1Password access
  — a running process's environment cannot be rewritten from outside it.
  This is unavoidable, not a bug; the shim's updated error message says
  exactly this and points at reconnecting via hlxc.
- **Touch ID / 1Password Desktop approval is still fully serial.** The
  broker threading fix (see "Broker threading" above) removes the
  *broker's own* serialization bug, but 1Password's own approval UI on
  the Mac still handles one prompt at a time — that's expected OS-level
  behavior, not something this bridge tries to parallelize, and it's now
  the only serialization left anywhere in the path.
- **Session-name pool is capped at 32.** The pre-flight tries
  `hermes-main`, `hermes-main-2`, ... `hermes-main-32`; if all 32 are
  attached simultaneously, name selection returns empty and hlxc falls
  back to plain `hermes-main` (i.e. a 33rd concurrent session collides
  with the first instead of getting its own path).

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

This was the original single-session verification pass, predating the
per-session socket paths described above. It remains accurate for the
pieces it tested (sshd drop-in, round-trip correctness, log discipline);
see "Verification (2026-09-07): multi-session" below for what changed.

## Verification (2026-09-07): multi-session

Verified against the live box with the new per-session pre-flight and
threaded broker in place:

- **Three concurrent `-R` forwards live simultaneously** — confirmed by
  `ls -l /run/hermes-op-broker/` showing three `srw-rw-rw-` sockets at
  once, one per hlxc window.
- A real `op` call through the shim as the unprivileged `hermes` user
  succeeded (`rc=0`) in all three concurrently-forwarded sessions.
- **Two genuinely concurrent real vault reads**
  (`op read op://Personal/Discord/password`) from two different sessions
  both returned `rc=0` with identical value hashes, overlapping in time
  (durations 1.29s and 2.39s, wall total 2.39s — the second request did
  not wait for the first to finish). The broker log shows both requests
  accepted before either completed, confirming the threading fix under a
  real concurrent load, not just the synthetic benchmark in "Broker
  threading" above.
- **Negative control:** a `su - hermes` login with no `OP_BROKER_SOCK`
  fails cleanly with the new two-mode diagnostic message described under
  "Per-session socket paths" above.
- **Stale-socket recovery** proven end to end (see "Stale-socket
  reaping" above for the exact failure/recovery sequence).
- **Reattach correctness** proven end to end (see "Per-session socket
  paths and the tmux-name rationale" above for the exact sequence).
- **Ansible deploy:** the playbook run for the four new
  `hermes_gateway` tasks (socket dir, tmpfiles.d drop-in, apply-tmpfiles
  now, remove legacy flat socket) completed with `RECAP ok=104
  changed=13 failed=0`. Post-deploy SSH confirmed the directory
  (`drwxr-xr-x root root`), the tmpfiles.d file, the deployed shim's hash
  matching the local source, and `streamlocalbindmask 0111`.

## Layer 3: ansible-playbook with zero on-disk secrets

Added 2026-09-13, on top of the same broker/socket/shim as Layers 1-2 — not
a new bridge, a new *consumer* of the existing `op` forwarding path.

### Why it exists

Fleet key coverage had a real gap: `id_ansible`'s pubkey was authorized on
some hosts but missing on 5 (proxy-01, frigate-01, gallery-01,
media-ingest-01/02) because the CT-provisioning mechanism (`pct exec`
piping a PVE host's own `authorized_keys` into new containers) had never
actually had `id_ansible` authorized on the PVE hosts themselves for two of
the three nodes at various points in the fleet's history. Fixed by
appending the key (never overwriting) to `/root/.ssh/authorized_keys` on
pve01/02/03 (cluster-replicated via `/etc/pve`, confirmed: one append
propagated to all 3) and via `pct exec` into the 5 gap containers, each
verified with a REAL ssh auth attempt (not just grepping the file) both
from the Mac and from hermes-gw-01.

Separately, hermes-gw-01 had accumulated two real secrets at rest from
earlier, less careful manual setup: a private copy of `id_ansible` at
`~hermes/.ssh/id_ansible` and a plaintext `ansible/.vault_pass`
(`M95b21D08!`) — both defeating the box's own "nothing secret on disk"
design goal. This layer replaces both with per-call 1Password sourcing and
the on-disk copies were removed (shredded, not just deleted).

### How it works

Three new files in `ansible/scripts/`:

- **`op-vault-pass.sh`** — Ansible natively supports pointing
  `--vault-password-file` (or `ANSIBLE_VAULT_PASSWORD_FILE`) at an
  EXECUTABLE: if the target has the exec bit set, Ansible runs it and
  reads stdout as the password, instead of reading file content directly.
  This script is that executable: `exec op read
  "op://Personal/6x2qdqloldso6yx75oba3t74qq/password"`. Requires
  `OP_BROKER_SOCK` (i.e. a live hlxc session) — refuses clearly otherwise.
- **`hlxc-ansible-playbook.sh`** / **`hlxc-ansible.sh`** — thin wrappers
  around `ansible-playbook` / `ansible` that additionally source the fleet
  SSH private key from 1Password into an EPHEMERAL agent for the
  duration of one run, never writing it to disk. Both delegate the actual
  work to `_hlxc_ansible_inner.sh`.
- **`_hlxc_ansible_inner.sh`** — the ssh-agent child process. Reads its
  config from environment variables the wrapper exported — deliberately
  NOT from string-interpolated shell fragments. This session hit two
  separate quoting bugs building this feature (SSH does not preserve
  argv quoting across a remote command line — a pubkey containing spaces
  got split into positional params and silently produced both a
  false-positive "already present" check AND garbage written into 5
  containers' `authorized_keys`; separately, a nested `bash -c '...'`
  string broke on a literal apostrophe) before landing on "real script
  file, env vars only, zero interpolation" as the only pattern that
  survived testing end to end.

Key mechanics, each empirically verified (not assumed) on 2026-09-13:

- **SSH key delivery:** `ssh-agent -t <ttl> <command>` execs `<command>`
  as its own real child and — this is standard OpenSSH behavior, not a
  guess — exits (removing its socket) when that child exits by ANY means,
  because the agent `wait()`s on that specific child PID. No trap/eval
  bookkeeping that a hard kill could skip. Inside, `op read <item> |
  ssh-add -t <ttl> -` pipes the key bytes directly into the agent via
  stdin; they never touch a file.
- **Identity selection — the part that looked simple and wasn't:**
  `ansible_ssh_private_key_file` is pointed DIRECTLY at
  `~/.ssh/id_ansible.pub` (the `.pub` file itself, no private key of that
  name existing anywhere on the box). This is what actually makes OpenSSH
  ask the agent for that one specific identity — confirmed via `-vvv`
  showing `identity file ...id_ansible.pub type 3` / `Offering public
  key: ...id_ansible.pub ... agent` / `Server accepts key`, reproduced
  both via raw `ssh` and via Ansible's own connection plugin (`ansible -m
  ping` → `SUCCESS` against frigate-01 and all 3 PVE nodes). A bare
  non-`.pub` path was tried FIRST and looked like it worked — until a
  negative-control test (decoy key loaded first in the agent, plus moving
  hermes-gw-01's own default identity out of the way) revealed the
  "success" was actually authenticating via a completely different,
  independently-authorized identity (see below), not the one under test.
  **Do not simplify this back to a bare path without re-running that
  negative control.**
- **Vault password:** `ANSIBLE_VAULT_PASSWORD_FILE` points at
  `op-vault-pass.sh` instead of `ansible.cfg`'s Mac-only plaintext
  `.vault_pass`.
- **`ControlPersist=no`:** the repo's default `ssh_args` keeps an
  authenticated multiplexed connection alive 60s after a run, reusable by
  any same-UID process with zero further auth — not acceptable for a
  bridge explicitly aiming for no standing access after the run ends, so
  it's disabled for these invocations only (Mac-side interactive usage
  keeps `ControlPersist=60s` for speed, unchanged).
- **`ANSIBLE_LOCAL_TEMP` on tmpfs (`/dev/shm`):** Ansible's default
  `local_tmp` lives under `~/.ansible/tmp` on the box's real disk and can
  transiently hold rendered content — including vaulted variables —
  during `template`/`copy` actions. Redirected to tmpfs so that content
  never touches a real block device even momentarily. Confirmed live
  during the end-to-end test below (`/dev/shm/hermes-ansible-local-tmp/...`
  appeared in the real diff output).
- **`ulimit -c 0`:** a crashed `ssh-agent` or `ansible-playbook` must not
  leave key material in a core dump.

### An unrelated finding surfaced during testing

hermes-gw-01's own SSH identity (`~/.ssh/id_ed25519`, generated for its
git/GitHub use and its `hermes_gateway_ssh_targets` role) turns out to
already be independently authorized as root on all 3 PVE hosts —
triplicated in each host's `authorized_keys`, most likely from `pmxcfs`
replication during separate provisioning runs at some point in the
fleet's history. This predates this session's work, is unrelated to the
1Password-sourced-secrets design, and was not introduced or removed by
it — flagged here because it's exactly the kind of standing access this
document should not let readers assume doesn't exist, and because it's
what caused the false-positive during identity-selection testing above.
Not fixed as part of this change; worth a deliberate decision later on
whether that access is intended.

### Verification (2026-09-13)

- **Key-coverage gap:** all 8 previously-unreachable hosts (pve01/02/03
  directly, plus proxy-01, frigate-01, gallery-01, media-ingest-01,
  media-ingest-02) now pass a REAL `ssh ... hostname` auth check with
  `id_ansible`, tested from both the Mac and from hermes-gw-01.
- **Negative controls:** wrapper refuses with a clear message when
  `OP_BROKER_SOCK` is unset (no hlxc session) and when a private key file
  reappears at `~/.ssh/id_ansible` (guards against regressing the
  no-secrets-on-disk property). A decoy SSH key loaded into the agent
  ahead of the real one is never offered when a specific `.pub` identity
  is requested with `IdentitiesOnly=yes`.
- **Real end-to-end run:** `hlxc-ansible-playbook.sh deploy_loadbalancer.yml
  --limit loadbalancer --check --diff`, run as the `hermes` user inside a
  genuine hlxc-forwarded socket (not simulated), against the real lb-01
  container: `PLAY RECAP: lb-01 ok=21 changed=2 unreachable=0 failed=0`.
  The diffed task (`Deploy Nginx Configuration`) renders a
  vault-decrypted variable, proving the vault-password path; the
  connection itself proves the SSH-key path; the temp file path in the
  diff output proves the tmpfs redirect.
- **Cleanup verified:** no `ssh-agent` process, no `id_ansible` private
  key, and no `ansible/.vault_pass` remain on hermes-gw-01 after the run.
- **Stray secrets removed:** the pre-existing on-disk `id_ansible`
  private key and plaintext `ansible/.vault_pass` (`M95b21D08!`) were
  shredded, not just deleted.

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
bridge already uses (whichever per-session path that pane's
`OP_BROKER_SOCK` points at), which carries SSH-channel traffic, not tty
bytes.

### How it works

Same architecture diagram as above, same shared local broker socket
(`~/.op-broker.sock`) and daemon process (`~/bin/op-broker.py`) behind
every per-session remote forward — no separate broker, no separate
tunnel per request type. The broker now dispatches on a `"type"` field in
the JSON request:

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
- **Each forwarded socket is world-accessible on hermes-gw-01, and any
  local user on that box can reach it.** Every reverse-forwarded socket is
  created by root's sshd, and the `StreamLocalBindMask 0111` sshd
  drop-in (`/etc/ssh/sshd_config.d/hermes-op-forward.conf`, described
  under "sshd prerequisite" above) makes each one land `srw-rw-rw-` —
  world read/write, not scoped to the `hermes` user. That mask exists
  because the unprivileged `hermes` user (who is not the SSH-login user)
  has to be able to reach a socket that root's sshd created on behalf of
  the SSH-login session; there is no narrower mask that still lets
  `hermes` connect. The practical consequence: **any local user on
  hermes-gw-01 can connect to any live session's socket and read the
  Mac's clipboard for as long as that hlxc session is live** — this is
  not hypothetical or theoretical, it follows directly from the socket's
  permission bits, and it applies per-session now rather than to a single
  shared socket. This was a consciously accepted tradeoff at design time,
  mitigated by the broker-side screen-lock refusal and size cap described
  above rather than by tightening the socket mask (tightening the mask
  would break the `hermes` user's own legitimate access, which is the
  entire point of the bridge).
- **Net assessment.** The clipboard bridge trades a real, unaudited
  read-access exposure (bounded by "hlxc session live" + "screen
  unlocked" + 24 MB) for tmux compatibility. It is materially weaker than
  the 1Password path on this page, which has no such exposure because
  every read requires the user's own physical Touch ID / security-key
  approval at the moment of the read. Anyone extending this bridge to
  carry additional request types should assume the same
  no-per-read-consent, any-local-user-on-the-box exposure applies unless
  a new type adds its own gate.
