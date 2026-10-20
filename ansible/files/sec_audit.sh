#!/bin/sh
# Second-pass security audit — the relationship/credential checks that a
# host-by-host sweep misses. Read-only. Run through ansible as root/become.
#
# Sections: ipv6, sudo gate, keys held, secrets at rest, ssh exposure.
h() { echo "## $1"; }

h IPV6
ip -6 addr show scope global 2>/dev/null | awk '/inet6/{print "v6_" $2 " scope=" $3 " " $4}'
ip -6 route show default 2>/dev/null | sed 's/^/v6_default_/'
echo "v6_forwarding=$(cat /proc/sys/net/ipv6/conf/all/forwarding 2>/dev/null)"

h SUDO_GATE
if [ -r /etc/pam.d/sudo ]; then
  grep -vE '^\s*(#|$)' /etc/pam.d/sudo | sed 's/^/pam_sudo_/'
fi
for f in /etc/security/sudo_keys/*; do
  [ -f "$f" ] || continue
  echo "sudo_keys_file=$f"
  ssh-keygen -lf "$f" 2>/dev/null | sed 's/^/sudo_key_/'
done
if id amd >/dev/null 2>&1; then
  echo "amd_passwd=$(passwd -S amd 2>/dev/null | awk '{print $2}')"
  sudo -l -U amd 2>/dev/null | grep -iE 'timestamp_timeout|tty_tickets|NOPASSWD|requiretty' | sed 's/^/sudo_policy_/'
fi
echo "sudoers_timestamp_ttl=$(grep -rhE '^\s*Defaults.*(timestamp_timeout|timestamp_type)' /etc/sudoers /etc/sudoers.d/ 2>/dev/null | tr '\n' ' ')"

h KEYS_HELD
# Private key material a compromise of THIS host would hand over.
find /root /home -xdev -type f \( -name 'id_*' -o -name '*.pem' -o -name '*.key' \) ! -name '*.pub' 2>/dev/null | sed 's/^/privkey_/' | head -20
echo "privkey_count=$(find /root /home -xdev -type f \( -name 'id_*' -o -name '*.pem' -o -name '*.key' \) ! -name '*.pub' 2>/dev/null | wc -l)"

h SECRETS_AT_REST
find /etc /opt /srv /usr/local -xdev -maxdepth 4 -type f \( -name '.env' -o -name '*.token' -o -name '*secret*' -o -name '*credential*' \) 2>/dev/null | sed 's/^/secretfile_/' | head -20
for f in $(find /etc /opt /srv /usr/local -xdev -maxdepth 4 -type f -name '.env' 2>/dev/null | head -10); do
  stat -c "env_perm $f %a %U:%G" "$f" 2>/dev/null
done

h SSH_EXPOSURE
echo "ssh_listen=$(ss -lnt 2>/dev/null | awk '$4 ~ /:22$/ {print $4}' | sort -u | tr '\n' ' ')"
echo "ssh_root_login=$(sshd -T 2>/dev/null | sed -n 's/^permitrootlogin //p')"
echo "authorized_keys_files=$(find /root /home -xdev -name authorized_keys 2>/dev/null | wc -l)"

h LISTENER_AUTH
# Anything listening on a wildcard address that is NOT sshd: name + port only.
ss -lntup 2>/dev/null | awk 'NR>1 && $5 ~ /^(0\.0\.0\.0|\*|\[::\]):/ {split($5,a,":"); print "wild_" $1 "_port_" a[length(a)] "_" $7}' | sed 's/users:((//; s/))//' | sort -u | head -25

h END
echo "sec_done=1"
exit 0
