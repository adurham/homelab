#!/usr/bin/env bash
# Same as hlxc-ansible-playbook.sh but wraps the ad-hoc `ansible` command
# instead of `ansible-playbook` (e.g. `ansible all -m ping`,
# `ansible pve_nodes -m shell -a uptime`). See hlxc-ansible-playbook.sh
# for the full design rationale -- this is a thin variant of the same
# mechanism, not a separate design.
set -euo pipefail
ulimit -c 0

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ANSIBLE_DIR="$REPO_ROOT/ansible"
INNER="$ANSIBLE_DIR/scripts/_hlxc_ansible_inner.sh"
TTL="${HLXC_ANSIBLE_KEY_TTL:-900}"

if [ -z "${OP_BROKER_SOCK:-}" ]; then
  echo "hlxc-ansible.sh: OP_BROKER_SOCK is not set -- attach via hlxc," \
       "not a plain ssh/su login." >&2
  exit 1
fi
if ! command -v op >/dev/null 2>&1; then
  echo "hlxc-ansible.sh: 'op' not found on PATH." >&2
  exit 1
fi

PUBKEY_IDENTITY="$HOME/.ssh/id_ansible"
if [ -f "$PUBKEY_IDENTITY" ]; then
  echo "hlxc-ansible.sh: refusing to run -- a PRIVATE key exists at" \
       "$PUBKEY_IDENTITY. This path must hold ONLY ${PUBKEY_IDENTITY}.pub." >&2
  exit 1
fi
if [ ! -f "${PUBKEY_IDENTITY}.pub" ]; then
  echo "hlxc-ansible.sh: missing ${PUBKEY_IDENTITY}.pub." >&2
  exit 1
fi

mkdir -p /dev/shm/hermes-ansible-local-tmp
chmod 700 /dev/shm/hermes-ansible-local-tmp

export HLXC_TTL="$TTL"
export HLXC_ANSIBLE_DIR="$ANSIBLE_DIR"
export HLXC_SSH_KEY_ITEM="op://Personal/5l6mt4hzy4ozgjqi7mgtzoedwq/password"
export HLXC_PUBKEY_IDENTITY_PUB="${PUBKEY_IDENTITY}.pub"
export HLXC_USE_ANSIBLE_ADHOC=1

exec ssh-agent -t "$TTL" "$INNER" "$@"
