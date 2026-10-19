#!/bin/bash
# Git signer for agent sessions: YubiKey first, 1Password fallback.
#
# Wired in as gpg.ssh.program by ~/.hermes/shell_init_git_sign.sh, so it only
# runs for automated commits; a human's own shells use ssh-keygen directly with
# the 1Password key from ~/.gitconfig.
#
# Signing: try the token. If the token is unplugged (ssh-keygen cannot reach the
# FIDO credential) retry the same signature with the 1Password-held key, which
# works whenever the app is unlocked. If that also fails, fail — never emit an
# unsigned commit.
#
# Anything that is not a signing call (e.g. `-Y verify` during `git
# verify-commit`) is passed straight through.

SSH_KEYGEN="${SSH_KEYGEN:-/opt/homebrew/bin/ssh-keygen}"
TOKEN_KEY="$HOME/.ssh/id_ed25519_sk_yk.pub"
FALLBACK_KEY="$HOME/.ssh/personal_macbook.pub"
LOG="$HOME/.hermes/logs/git-sign.log"

if [ "${1:-}" != "-Y" ] || [ "${2:-}" != "sign" ]; then
    exec "$SSH_KEYGEN" "$@"
fi

# Which key did git ask for? (the argument after -f)
key=""; prev=""
for a in "$@"; do
    [ "$prev" = "-f" ] && key="$a"
    prev="$a"
done

"$SSH_KEYGEN" "$@" && exit 0
rc=$?

# Only the token key falls back. Any other key's failure is real.
case "$(basename "${key:-}")" in
    id_ed25519_sk_yk*) ;;
    *) exit "$rc" ;;
esac
[ -r "$FALLBACK_KEY" ] || exit "$rc"

# Rebuild the argv with -f <1Password key>.
args=(); prev=""
for a in "$@"; do
    if [ "$prev" = "-f" ]; then args+=("$FALLBACK_KEY"); else args+=("$a"); fi
    prev="$a"
done

mkdir -p "$(dirname "$LOG")" 2>/dev/null
printf '%s token signing failed (rc=%s) -> falling back to 1Password\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$rc" >> "$LOG" 2>/dev/null

exec "$SSH_KEYGEN" "${args[@]}"
