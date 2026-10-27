#!/usr/bin/env bash
# vault_get.sh -- print ONE value from the ansible vault, without caring how it is quoted.
#
# Why this exists: the vault mixes quoted (`key: "value"`) and unquoted (`key: value`)
# scalars. Ad-hoc extraction (`awk -F'"' ...`) silently returns an EMPTY string for an
# unquoted key, which then fails downstream as a wrong password / wrong token instead of
# as a parsing error. Always read vault values through this helper.
#
# Usage:
#   scripts/vault_get.sh <vault-key> [vault-file]
#
# Env overrides:
#   VAULT_FILE       default: <repo>/ansible/group_vars/all/vault.yml
#   VAULT_PASS_FILE  default: <repo>/.vault_pass
#
# Exit codes: 0 = value printed, 2 = key missing, 3 = key present but empty,
#             4 = decrypt/parse failure. Never prints the value on error.
set -euo pipefail

key="${1:?usage: vault_get.sh <vault-key> [vault-file]}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"

vault_file="${2:-${VAULT_FILE:-${repo_root}/ansible/group_vars/all/vault.yml}}"
pass_file="${VAULT_PASS_FILE:-${repo_root}/.vault_pass}"

[ -r "${vault_file}" ] || { echo "vault_get: cannot read vault file ${vault_file}" >&2; exit 4; }
[ -r "${pass_file}" ] || { echo "vault_get: cannot read pass file ${pass_file}" >&2; exit 4; }

ansible-vault view "${vault_file}" --vault-password-file "${pass_file}" 2>/dev/null \
  | VAULT_KEY="${key}" python3 -c '
import os, sys, yaml

key = os.environ["VAULT_KEY"]
try:
    data = yaml.safe_load(sys.stdin)
except Exception as exc:
    print(f"vault_get: YAML parse failure: {exc}", file=sys.stderr)
    sys.exit(4)
if not isinstance(data, dict):
    print("vault_get: vault did not parse to a mapping", file=sys.stderr)
    sys.exit(4)
if key not in data:
    print(f"vault_get: key not found: {key}", file=sys.stderr)
    sys.exit(2)
value = data[key]
if value is None or value == "":
    print(f"vault_get: key present but empty: {key}", file=sys.stderr)
    sys.exit(3)
if isinstance(value, (dict, list)):
    print(f"vault_get: key is not a scalar ({type(value).__name__}): {key}", file=sys.stderr)
    sys.exit(4)
sys.stdout.write(str(value) + "\n")
'
