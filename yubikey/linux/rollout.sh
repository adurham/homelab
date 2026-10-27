#!/bin/bash
# Token-gated sudo rollout (idempotent). Run as root on a Debian/Ubuntu host.
#
# Phase 1 (default): install the PAM module, create the `amd` login user, copy the
# login keys, write the TOKEN-ONLY sudo key file, install the sudo PAM stack and
# lock amd's password. Root's keys and sshd are NOT touched — root access stays as
# the backstop until the new path is proven from a fresh session.
#
# Phase 2 (--finish): the later step. Adds the sshd drop-ins (root login off,
# password auth off), inserts the Include line when the distro config lacks it,
# validates with `sshd -t`, then empties root's authorized_keys (backup kept).
# Run this ONLY after `ssh -A amd@host 'sudo id'` has returned root from a fresh
# login on that host.
#
# Usage:
#   rollout.sh --token-key /root/sk.pub [--module /tmp/pam_ssh_agent.so] \
#              [--login-keys /root/.ssh/authorized_keys] [--finish]
#
# The PAM module is a Rust build of https://github.com/nresare/pam-ssh-agent
# (see README.md — the distro's libpam-ssh-agent-auth cannot parse sk keys).
set -euo pipefail

MODULE=/tmp/pam_ssh_agent.so
TOKEN_KEY=""
LOGIN_KEYS=""
FINISH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --module)     MODULE="$2"; shift 2 ;;
    --token-key)  TOKEN_KEY="$2"; shift 2 ;;
    --login-keys) LOGIN_KEYS="$2"; shift 2 ;;
    --finish)     FINISH=1; shift ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

[ -f "$MODULE" ] || { echo "module not found: $MODULE" >&2; exit 1; }

# ---------------- phase 1: login user + sudo gate ----------------
install -o root -g root -m 0644 "$MODULE" /lib/x86_64-linux-gnu/security/pam_ssh_agent.so

id amd >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo amd
install -d -m 0700 -o amd -g amd /home/amd/.ssh

if [ -n "$LOGIN_KEYS" ]; then
  [ -f "$LOGIN_KEYS" ] || { echo "login keys not found: $LOGIN_KEYS" >&2; exit 1; }
  cp "$LOGIN_KEYS" /home/amd/.ssh/authorized_keys
fi
chown amd:amd /home/amd/.ssh/authorized_keys
chmod 0600 /home/amd/.ssh/authorized_keys

# the sudo gate: TOKEN ONLY, root-owned (never a user-writable file)
[ -n "$TOKEN_KEY" ] || { echo "--token-key is required (the sk-ssh-ed25519 public key)" >&2; exit 1; }
install -d -m 0755 -o root -g root /etc/security/sudo_keys
grep -F 'sk-ssh-ed25519@openssh.com' "$TOKEN_KEY" > /etc/security/sudo_keys/amd
[ -s /etc/security/sudo_keys/amd ] || { echo "no sk- key found in $TOKEN_KEY" >&2; exit 1; }
chmod 0644 /etc/security/sudo_keys/amd

printf 'Defaults env_keep += "SSH_AUTH_SOCK"\n%%sudo ALL=(ALL:ALL) ALL\n' > /etc/sudoers.d/10-agent
chmod 0440 /etc/sudoers.d/10-agent
visudo -cf /etc/sudoers.d/10-agent >/dev/null

[ -f /etc/pam.d/sudo.pam_yk.bak ] || cp /etc/pam.d/sudo /etc/pam.d/sudo.pam_yk.bak
cat > /etc/pam.d/sudo <<'PAMEOF'
#%PAM-1.0
# Token-gated sudo: pam_ssh_agent must sign a challenge with the YubiKey key
# listed in /etc/security/sudo_keys/<user>. No pam_deny: failure falls through
# to the normal password stack.
auth     sufficient  pam_ssh_agent.so file=/etc/security/sudo_keys/%u
session  required    pam_env.so readenv=1 user_readenv=0
session  required    pam_env.so readenv=1 envfile=/etc/default/locale user_readenv=0
@include common-auth
@include common-account
@include common-session-noninteractive
PAMEOF
chmod 0644 /etc/pam.d/sudo

# `sudo -i` uses its OWN PAM stack (/etc/pam.d/sudo-i). Unpatched, it falls through
# to the password stack, amd's password is locked, and a root login shell becomes
# impossible while plain `sudo cmd` works — an inconsistent, confusing failure.
if [ -f /etc/pam.d/sudo-i ] && ! grep -q pam_ssh_agent /etc/pam.d/sudo-i; then
  cp /etc/pam.d/sudo-i "/etc/pam.d/sudo-i.bak-$(date +%Y%m%d)"
  { printf 'auth     sufficient  pam_ssh_agent.so file=/etc/security/sudo_keys/%%u\n';
    cat "/etc/pam.d/sudo-i.bak-$(date +%Y%m%d)"; } > /etc/pam.d/sudo-i
  chmod 0644 /etc/pam.d/sudo-i
fi

passwd -l amd >/dev/null 2>&1 || true
echo "phase1 done: $(hostname) — $(id amd | cut -d' ' -f1)"

if [ "$FINISH" -ne 1 ]; then
  cat <<'NEXT'
Now prove the new path from a FRESH session before finishing:
    ssh -A amd@<host> 'sudo id'          # must return uid=0 with no password
    ssh amd@<host> 'id'                  # must work without the token too
Then re-run with --finish.
NEXT
  exit 0
fi

# ---------------- phase 2: sshd hardening + root SSH off ----------------
# Containers built from some Ubuntu images have NO `Include sshd_config.d/*.conf`
# line, so a drop-in silently does nothing. Insert it FIRST (first-obtained-wins).
[ -f /etc/ssh/sshd_config.bak-$(date +%Y%m%d) ] || cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak-$(date +%Y%m%d)
grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config \
  || sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
install -d -m 0755 /etc/ssh/sshd_config.d
printf 'PermitRootLogin no\n' > /etc/ssh/sshd_config.d/00-no-root.conf
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  > /etc/ssh/sshd_config.d/99-harden.conf
chmod 0644 /etc/ssh/sshd_config.d/00-no-root.conf /etc/ssh/sshd_config.d/99-harden.conf

sshd -t   # refuse to continue on a bad config

# socket-activated sshd re-reads config per connection; non-socket hosts need a reload
if systemctl is-active --quiet ssh.socket; then :; else systemctl reload ssh 2>/dev/null || systemctl reload sshd; fi

[ -f "/root/authorized_keys.bak-$(date +%Y%m%d)" ] || cp /root/.ssh/authorized_keys "/root/authorized_keys.bak-$(date +%Y%m%d)" 2>/dev/null || true
: > /root/.ssh/authorized_keys

sshd -T | grep -E '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication)'
echo "phase2 done: $(hostname) — root SSH off, password auth off"
