#!/usr/bin/env bash
# INNER step of hlxc-ansible-playbook.sh -- do not run directly.
#
# Runs as the child of `ssh-agent -t <ttl>` (see the outer script). Reads
# its configuration from environment variables the outer script exported
# (never from string-interpolated shell fragments -- see the outer
# script's header for why that pattern is deliberately avoided here).
#
# Required env vars (set by hlxc-ansible-playbook.sh):
#   HLXC_TTL                 key/vault-password lifetime in seconds
#   HLXC_ANSIBLE_DIR         path to the ansible/ directory
#   HLXC_SSH_KEY_ITEM        1Password item ref for the fleet SSH private key
#   HLXC_PUBKEY_IDENTITY_PUB path to id_ansible.pub (identity selector)
set -euo pipefail

: "${HLXC_TTL:?not set}"
: "${HLXC_ANSIBLE_DIR:?not set}"
: "${HLXC_SSH_KEY_ITEM:?not set}"
: "${HLXC_PUBKEY_IDENTITY_PUB:?not set}"

op read "$HLXC_SSH_KEY_ITEM" | ssh-add -t "$HLXC_TTL" - >/dev/null

export ANSIBLE_VAULT_PASSWORD_FILE="$HLXC_ANSIBLE_DIR/scripts/op-vault-pass.sh"
export ANSIBLE_LOCAL_TEMP=/dev/shm/hermes-ansible-local-tmp
export ANSIBLE_SSH_ARGS="-o ControlMaster=auto -o ControlPersist=no -o IdentitiesOnly=yes"

cd "$HLXC_ANSIBLE_DIR"
if [ "${HLXC_USE_ANSIBLE_ADHOC:-0}" = "1" ]; then
  exec ansible -e ansible_ssh_private_key_file="$HLXC_PUBKEY_IDENTITY_PUB" "$@"
else
  exec ansible-playbook -e ansible_ssh_private_key_file="$HLXC_PUBKEY_IDENTITY_PUB" "$@"
fi
