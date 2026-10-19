#!/bin/bash
# Token-gated sudo rollout step (idempotent). Run as root on a Debian/Ubuntu host.
# Does NOT touch root's authorized_keys or sshd: root access stays as the backstop
# until the new path is proven on every host.
set -euo pipefail

install -o root -g root -m 0644 /tmp/pam_ssh_agent.so /lib/x86_64-linux-gnu/security/pam_ssh_agent.so

id amd >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo amd
install -d -m 0700 -o amd -g amd /home/amd/.ssh

# login keys: whatever root has (token + 1Password) so login works without the token
cp /root/.ssh/authorized_keys /home/amd/.ssh/authorized_keys
chown amd:amd /home/amd/.ssh/authorized_keys
chmod 0600 /home/amd/.ssh/authorized_keys

# the sudo gate: TOKEN ONLY, root-owned (never a user-writable file)
install -d -m 0755 -o root -g root /etc/security/sudo_keys
grep "sk-ssh-ed25519" /root/.ssh/authorized_keys > /etc/security/sudo_keys/amd
chmod 0644 /etc/security/sudo_keys/amd
grep -q "sk-ssh-ed25519" /etc/security/sudo_keys/amd

printf 'Defaults env_keep += "SSH_AUTH_SOCK"\n%%sudo ALL=(ALL:ALL) ALL\n' > /etc/sudoers.d/10-agent
chmod 0440 /etc/sudoers.d/10-agent
visudo -cf /etc/sudoers.d/10-agent >/dev/null

[ -f /etc/pam.d/sudo.pam_yk.bak ] || cp /etc/pam.d/sudo /etc/pam.d/sudo.pam_yk.bak
install -o root -g root -m 0644 /tmp/sudo_pam /etc/pam.d/sudo

echo "configured: $(hostname) ($(id amd | cut -d' ' -f1))"
