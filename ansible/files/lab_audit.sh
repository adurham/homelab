#!/bin/sh
# Lab security sweep — read-only host audit.
#
# Run through ansible (`ansible all -m ansible.builtin.script -a <this file>`)
# or directly on a host. Prints `KEY=VALUE` / list lines, exits 0 always so a
# missing binary on one distro never aborts the run for the whole fleet.
#
# Lives in the repo (not /tmp) because the 2026-10-20 MacBook crash lost the
# previous copy and there was no way to reproduce sweep #2's numbers exactly.
#
# Sections: identity, ssh, accounts, sudo, keys, firewall, listeners,
# packages, systemd, suid, docker, time, tailscale, auth-failures.
# PVE-only extras are gated on /usr/bin/pveversion.

h() { echo "## $1"; }
v() { printf '%s=' "$1"; shift; "$@" 2>/dev/null | tr '\n' ' ' | cut -c1-400; echo; }

h IDENTITY
echo "host=$(hostname 2>/dev/null || uname -n)"
v kernel uname -r
echo "os=$(. /etc/os-release 2>/dev/null; echo "${ID:-?}${VERSION_ID:-}")"
v virt systemd-detect-virt
echo "uptime_days=$(awk '{printf "%d", $1/86400}' /proc/uptime 2>/dev/null)"

h SSH_EFFECTIVE
if sshd -T >/dev/null 2>&1; then
  sshd -T 2>/dev/null | grep -Ei '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication|permitemptypasswords|x11forwarding|allowusers|allowgroups|listenaddress|maxauthtries)' | sed 's/^/ssh_/'
else
  echo ssh_effective=UNAVAILABLE_NOT_ROOT
  grep -hEi '^\s*(PasswordAuthentication|PermitRootLogin|PubkeyAuthentication|PermitEmptyPasswords)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | sed 's/^/ssh_config_/'
fi
echo "ssh_dropins=$(ls /etc/ssh/sshd_config.d/*.conf 2>/dev/null | wc -l)"

h ACCOUNTS
echo "uid0=$(awk -F: '$3==0{printf "%s ", $1}' /etc/passwd)"
echo "login_shells=$(awk -F: '$7 !~ /(nologin|false|sync|shutdown|halt)$/ {printf "%s ", $1}' /etc/passwd)"
if [ "$(id -u)" = 0 ]; then
  echo "empty_pw=$(awk -F: '$2==""{printf "%s ", $1}' /etc/shadow 2>/dev/null)"
  echo "locked=$(awk -F: '$2 ~ /^[!*]/{printf "%s ", $1}' /etc/shadow 2>/dev/null | cut -c1-200)"
fi
echo "sudo_group=$(getent group sudo wheel 2>/dev/null | awk -F: '{printf "%s:%s ", $1, $4}')"

h SUDOERS
if [ "$(id -u)" = 0 ]; then
  grep -rhE '^[^#].*NOPASSWD' /etc/sudoers /etc/sudoers.d/ 2>/dev/null | tr -s ' ' | cut -c1-200 | sed 's/^/nopasswd_/'
  echo "sudoers_d_files=$(ls /etc/sudoers.d/ 2>/dev/null | tr '\n' ' ')"
  for f in /etc/sudoers /etc/sudoers.d/*; do [ -f "$f" ] && stat -c "sudoers_perm $f %a %U:%G" "$f"; done 2>/dev/null
fi

h KEYS
for u in root amd; do
  k=/root/.ssh/authorized_keys; [ "$u" = amd ] && k="$(getent passwd amd | cut -d: -f6)/.ssh/authorized_keys"
  if [ -f "$k" ]; then
    n=$(grep -cE '^(ssh-|ecdsa-|sk-)' "$k" 2>/dev/null)
    echo "keys_${u}=$n"
    awk '/^(ssh-|ecdsa-|sk-)/{print $NF}' "$k" 2>/dev/null | sed "s/^/key_${u}_comment_/"
  else
    echo "keys_${u}=NONE"
  fi
done
stat -c 'ssh_dir_perm %n %a %U:%G' /root/.ssh ~amd/.ssh 2>/dev/null

h FIREWALL
echo "ufw=$(ufw status 2>/dev/null | head -1)"
echo "firewalld=$(systemctl is-active firewalld 2>/dev/null)"
echo "nftables=$(systemctl is-enabled nftables 2>/dev/null):$(systemctl is-active nftables 2>/dev/null)"
echo "nft_rules=$(nft list ruleset 2>/dev/null | wc -l)"
echo "iptables_rules=$(iptables -S 2>/dev/null | wc -l)"
echo "ipt_persist=$(systemctl is-enabled netfilter-persistent 2>/dev/null)"

h LISTENERS
ss -lntu 2>/dev/null | awk 'NR>1{print $1, $5}' | sort -u | sed 's/^/listen_/' | head -40
echo "listen_wild=$(ss -lntu 2>/dev/null | awk 'NR>1 && ($5 ~ /^0\.0\.0\.0:|^\*:|^\[::\]:/){c++} END{print c+0}')"

h PACKAGES
if command -v apt-get >/dev/null 2>&1; then
  echo "pkgmgr=apt"
  echo "pending=$(apt-get -s upgrade 2>/dev/null | grep -c '^Inst')"
  echo "pending_security=$(apt-get -s upgrade 2>/dev/null | grep '^Inst' | grep -ci security)"
  echo "reboot_required=$([ -f /var/run/reboot-required ] && echo yes || echo no)"
  echo "unattended=$(systemctl is-active unattended-upgrades 2>/dev/null)"
elif command -v dnf >/dev/null 2>&1; then
  echo "pkgmgr=dnf"
  echo "pending=$(dnf -q check-update 2>/dev/null | grep -cE '^[a-zA-Z0-9]')"
  echo "reboot_required=$( [ -f /var/run/reboot-required ] && echo yes || echo no )"
elif command -v zypper >/dev/null 2>&1; then
  echo "pkgmgr=zypper"
  echo "pending=$(zypper -q lu 2>/dev/null | grep -c '^v ')"
fi

h SYSTEMD
echo "failed_units=$(systemctl --failed --no-legend 2>/dev/null | wc -l)"
systemctl --failed --no-legend 2>/dev/null | awk '{print "failed_", $1}' | head -10
echo "world_writable_units=$(find /etc/systemd/system /lib/systemd/system -maxdepth 2 -name '*.service' -perm -o+w 2>/dev/null | head -10 | tr '\n' ' ')"
echo "timers=$(systemctl list-timers --no-legend 2>/dev/null | wc -l)"

h SUID
if [ "$(id -u)" = 0 ]; then
  echo "suid_count=$(find / -xdev -perm -4000 -type f 2>/dev/null | wc -l)"
  find / -xdev -perm -4000 -type f 2>/dev/null | grep -vE '^/(usr|bin|sbin)/' | sed 's/^/suid_odd_/' | head -10
  find /etc /usr/local /opt -xdev -type d -perm -0002 2>/dev/null | sed 's/^/world_writable_dir_/' | head -10
fi

h DOCKER
echo "docker=$(systemctl is-active docker 2>/dev/null)"
stat -c 'docker_sock %n %a %U:%G' /var/run/docker.sock 2>/dev/null
echo "podman=$(command -v podman >/dev/null && echo yes || echo no)"

h TIME
echo "timesync=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)"
echo "chrony=$(systemctl is-active chrony 2>/dev/null):$(systemctl is-active systemd-timesyncd 2>/dev/null)"

h TAILSCALE
if command -v tailscale >/dev/null 2>&1; then
  echo "ts_state=$(tailscale status --json 2>/dev/null | tr -d '\n' | sed -n 's/.*"BackendState":"\([A-Za-z]*\)".*/\1/p')"
  echo "ts_ip4=$(tailscale ip -4 2>/dev/null | head -1)"
  echo "ts_routes=$(tailscale status --json 2>/dev/null | tr -d '\n' | sed -n 's/.*"PrimaryRoutes":\[\([^]]*\)\].*/\1/p' | cut -c1-160)"
else
  echo "ts_state=absent"
fi

h AUTH_FAILURES
# Match the sshd syslog line only. A bare `grep 'Failed password'` also
# matches Loki/Grafana log lines that QUOTE the alert query string
# (`|~ "Failed password|Invalid user"`), which is how sweep 3 reported a
# phantom 6066 failures on vm-01 and 1298 on graf-01 — those hosts run the
# log pipeline, every other host reported 0.
echo "ssh_fail_24h=$(journalctl --since '-24h' --no-pager 2>/dev/null | grep -cE '\ssshd\[[0-9]+\]:.*(Failed password|Invalid user)')"
echo "sudo_denied_24h=$(journalctl --since '-24h' --no-pager 2>/dev/null | grep -cE '\ssudo\[[0-9]+\]:.*(incorrect password|NOT in sudoers)')"

h PVE
if [ -x /usr/bin/pveversion ]; then
  v pve pveversion
  echo "quorum=$(pvecm status 2>/dev/null | sed -n 's/^Quorate: *//p')"
  echo "ha=$(ha-manager status 2>/dev/null | head -3 | tr '\n' ' ')"
  echo "pve_fw=$(systemctl is-active pve-firewall 2>/dev/null)"
  echo "pve_tfa_users=$(pveum user list --output-format json 2>/dev/null | tr ',' '\n' | grep -c '"tfa"')"
  echo "root_pam_tfa=$(pveum user tfa list root@pam 2>/dev/null | wc -l)"
  stat -c 'pve_priv %n %a %U:%G' /etc/pve/priv 2>/dev/null
  echo "--- replication ---"
  pvesr status 2>/dev/null | awk 'NR>1{print "repl_", $1, $NF}' | head -20
  echo "--- backup jobs ---"
  pvesh get /cluster/backup --output-format json 2>/dev/null | tr '}' '\n' | grep -c '"enabled":1' | sed 's/^/backup_jobs_enabled=/'
fi

h END
echo "sweep_done=1"
exit 0
