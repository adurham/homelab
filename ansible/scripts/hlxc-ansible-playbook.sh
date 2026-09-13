#!/usr/bin/env bash
# Run ansible-playbook from hermes-gw-01 with BOTH the fleet SSH key and
# the vault password sourced live from 1Password on the Mac -- nothing
# secret ever touches this box's disk, not even transiently.
#
# Requires an active hlxc session (OP_BROKER_SOCK set) -- see
# docs/1password-hlxc-bridge.md. Every run means two fresh Touch ID /
# security-key approvals on the Mac (one for the SSH key, one per vault
# password read -- Ansible may re-invoke the vault script more than once
# per run, each a separate approval).
#
# Usage: same as ansible-playbook, e.g.:
#   scripts/hlxc-ansible-playbook.sh site.yml --limit pve_nodes
#
# Design notes:
#   - SSH key: `op read <item> | ssh-add -t <ttl> -` into an EPHEMERAL
#     agent created via `ssh-agent -t <ttl> <command> [args]`. Standard
#     OpenSSH ssh-agent behavior: it execs <command> as a real child and,
#     because it wait()s on that specific child PID, notices and exits
#     (removing its socket) when that child exits BY ANY MEANS -- normal
#     exit, error, or being killed -- not just on a clean trap path. The
#     work happens in _hlxc_ansible_inner.sh, a real file passed as
#     ssh-agent's command argument (not a quoted string), specifically to
#     avoid multi-layer shell-quoting bugs: this repo hit two separate
#     quoting bugs in one session (SSH not preserving argv quoting when
#     building a remote command line, and a nested `bash -c '...'` string
#     silently breaking on a literal apostrophe) before landing on
#     "real script file + exported env vars, zero string interpolation
#     into code executed by a later shell" as the only pattern that
#     survived testing. Do not collapse this back into an inline `bash -c`
#     one-liner without re-testing end-to-end.
#   - Identity selection: ansible_ssh_private_key_file is pointed DIRECTLY
#     at ~/.ssh/id_ansible.pub (the .pub file itself -- no private key of
#     that name exists on this box at all). Empirically verified
#     2026-09-13 against a real CT with ONLY id_ansible authorized, a
#     decoy key loaded in the agent ahead of the real one, hermes-gw-01's
#     own default identity (~/.ssh/id_ed25519, separately authorized on
#     the PVE hosts -- see below) moved out of the way, and
#     IdentitiesOnly=yes: OpenSSH reads the given .pub, computes its
#     fingerprint, and asks the agent specifically for that identity --
#     "identity file ...id_ansible.pub type 3" / "Offering public key:
#     ...id_ansible.pub ... agent" / "Server accepts key" in -vvv output,
#     confirmed both via raw ssh AND via Ansible's own ssh connection
#     plugin (ansible -m ping SUCCESS against frigate-01 and all 3 pve
#     nodes). A bare path with NO .pub suffix (pointing at a filename with
#     only a PRIVATE key present, or no file at all) does NOT reliably
#     trigger this -- it was tried first and produced a false-positive
#     success by silently authenticating via a DIFFERENT identity
#     (hermes-gw-01's own id_ed25519, which turned out to be separately,
#     independently authorized as root on all 3 PVE hosts already -- see
#     FORK.md 2026-09-13 for that finding). Always pass the .pub path
#     explicitly; never "simplify" this without re-running the decoy +
#     moved-default-identity test in this comment block.
#   - Vault password: ANSIBLE_VAULT_PASSWORD_FILE points at
#     scripts/op-vault-pass.sh (an executable Ansible runs and reads
#     stdout from, per Ansible's own vault-password-file-as-executable
#     support) instead of ansible.cfg's Mac-only plaintext .vault_pass.
#   - ControlPersist=no: the repo's default ssh_args keeps an
#     authenticated multiplexed connection alive 60s after a normal run,
#     reusable by any same-UID process with no further auth. Not
#     acceptable for a bridge that specifically aims for zero standing
#     access after the run ends, so it's turned off for these invocations
#     (slower on multi-play runs; accepted, deliberate tradeoff for this
#     bridge only -- unrelated to the Mac's own normal interactive usage,
#     which keeps ControlPersist=60s for speed).
#   - ANSIBLE_LOCAL_TEMP on tmpfs (/dev/shm): Ansible's default local_tmp
#     lives under ~/.ansible/tmp on the box's real disk and can
#     transiently hold rendered content (including vaulted variables)
#     during template/copy actions. Redirected to tmpfs so that content
#     never hits a real block device even momentarily.
#   - `ulimit -c 0`: a crashed ssh-agent or ansible-playbook process must
#     not leave key material in a core dump on disk.
#
# Known residual limitations (same-UID exposure), not solved here:
#   - The ephemeral agent's socket, like the op-broker socket, is only as
#     safe as "no other process running as the hermes user reads it during
#     this run's lifetime" -- any such process could ask the agent to sign
#     with the loaded identity while it's alive. Bounded by the TTL below.
#   - 2GB swap is enabled on this box; ssh-agent does not mlock key memory
#     on Linux, so under memory pressure the key could theoretically be
#     paged to swap for the run's duration. Not mitigated here (disabling
#     swap is a box-wide change outside this script's scope) -- flagged as
#     a residual risk, not a solved one.
#   - hermes-gw-01's own SSH identity (~/.ssh/id_ed25519) is independently
#     authorized as root on pve01/02/03 (found 2026-09-13, pre-existing,
#     not introduced by this change) -- this script does not depend on or
#     remove that access, but it means "hermes-gw-01 can reach the PVE
#     hosts" was already true before this bridge existed. Flagged for
#     awareness, not fixed here (out of scope: unrelated standing access,
#     not part of the 1Password-sourced-secrets design).
set -euo pipefail
ulimit -c 0

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ANSIBLE_DIR="$REPO_ROOT/ansible"
INNER="$ANSIBLE_DIR/scripts/_hlxc_ansible_inner.sh"
TTL="${HLXC_ANSIBLE_KEY_TTL:-900}"   # 15 min default -- long enough for a full playbook run, short-lived if leaked

if [ -z "${OP_BROKER_SOCK:-}" ]; then
  echo "hlxc-ansible-playbook.sh: OP_BROKER_SOCK is not set -- attach via" \
       "hlxc, not a plain ssh/su login." >&2
  exit 1
fi
if ! command -v op >/dev/null 2>&1; then
  echo "hlxc-ansible-playbook.sh: 'op' not found on PATH." >&2
  exit 1
fi

PUBKEY_IDENTITY="$HOME/.ssh/id_ansible"
if [ -f "$PUBKEY_IDENTITY" ]; then
  echo "hlxc-ansible-playbook.sh: refusing to run -- a PRIVATE key exists at" \
       "$PUBKEY_IDENTITY. This path must hold ONLY ${PUBKEY_IDENTITY}.pub" \
       "(used to select the right agent identity); a private key there" \
       "defeats the whole point of this script. Remove it." >&2
  exit 1
fi
if [ ! -f "${PUBKEY_IDENTITY}.pub" ]; then
  echo "hlxc-ansible-playbook.sh: missing ${PUBKEY_IDENTITY}.pub -- needed" \
       "to select the right identity from the agent." >&2
  exit 1
fi

mkdir -p /dev/shm/hermes-ansible-local-tmp
chmod 700 /dev/shm/hermes-ansible-local-tmp

export HLXC_TTL="$TTL"
export HLXC_ANSIBLE_DIR="$ANSIBLE_DIR"
export HLXC_SSH_KEY_ITEM="op://Personal/5l6mt4hzy4ozgjqi7mgtzoedwq/password"
export HLXC_PUBKEY_IDENTITY_PUB="${PUBKEY_IDENTITY}.pub"

exec ssh-agent -t "$TTL" "$INNER" "$@"
