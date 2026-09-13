#!/usr/bin/env bash
# Ansible vault-password-file provider, backed by 1Password.
#
# Ansible supports pointing --vault-password-file (or the
# ANSIBLE_VAULT_PASSWORD_FILE env var) at an EXECUTABLE script instead of a
# plain file: if the target has the executable bit set, ansible runs it and
# reads stdout as the password instead of reading file contents directly.
# This script is that executable -- it holds no secret itself, only the
# 1Password item reference (an id, not a credential) needed to fetch one at
# call time.
#
# Requires an active hlxc session (OP_BROKER_SOCK set in the environment) so
# the `op` on PATH is the hlxc bridge shim forwarding to the real `op` CLI on
# the Mac -- see docs/1password-hlxc-bridge.md. Every call means a fresh
# Touch ID / security-key approval on the Mac; nothing is cached here.
#
# Item: "Ansible Vault Password (homelab)" (Personal vault) -- decrypts
# ansible/group_vars/all/vault.yml. See warm memory fact 2205 / repo fact 5.
set -euo pipefail

if [ -z "${OP_BROKER_SOCK:-}" ]; then
  echo "op-vault-pass.sh: OP_BROKER_SOCK is not set -- this must run inside" \
       "an hlxc session (attach via hlxc, not a plain ssh/su login)." >&2
  exit 1
fi

if ! command -v op >/dev/null 2>&1; then
  echo "op-vault-pass.sh: 'op' not found on PATH." >&2
  exit 1
fi

exec op read "op://Personal/6x2qdqloldso6yx75oba3t74qq/password"
