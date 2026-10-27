#!/usr/bin/env bash
# kernel-parity.sh -- do the three PVE nodes agree on the kernel?
#
# Why: on 2026-10-19 a rolling `dist-upgrade` ran on all three nodes minutes apart
# WITHOUT refreshing the package lists on each node first. pve01's index already
# knew about 7.0.14-25 and installed it; pve02/pve03 were on an older index and
# installed 7.0.14-24. Same command, three nodes, two kernels -- and nine days
# later pve01 was the only node that stalled its NIC and fenced itself.
#
# This script refreshes the indexes and compares, for every node:
#   * running kernel            (uname -r)
#   * installed meta version    (dpkg-query proxmox-kernel-7.0)
#   * upgrade candidate         (apt-cache policy proxmox-kernel-7.0)
# It exits non-zero when running or installed versions disagree. It upgrades
# nothing.
#
# Usage: scripts/proxmox/kernel-parity.sh [--no-update]
# Requires: ~/.ssh/id_ansible and agent forwarding (sudo is token-gated), amd login.

set -uo pipefail

NODES=${PVE_NODES:-"192.168.86.11 192.168.86.12 192.168.86.13"}
KEY=${PVE_KEY:-$HOME/.ssh/id_ansible}
UPDATE=1
[ "${1:-}" = "--no-update" ] && UPDATE=0

ssh_node() { # $1=ip $2=command
  ssh -A -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=8 \
      "amd@$1" "sudo sh -c '$2'" 2>/dev/null | tr -d '\r'
}

TMP=$(mktemp -t kernel-parity.XXXXXX)
trap 'rm -f "$TMP"' EXIT
fail=0

for ip in $NODES; do
  name=$(ssh_node "$ip" 'hostname')
  if [ -z "$name" ]; then
    printf '%-15s UNREACHABLE\n' "$ip"
    fail=1
    continue
  fi

  [ "$UPDATE" -eq 1 ] && ssh_node "$ip" 'apt-get update -qq' >/dev/null

  run=$(ssh_node "$ip" 'uname -r')
  inst=$(ssh_node "$ip" 'dpkg-query -W proxmox-kernel-7.0 2>/dev/null | cut -f2')
  cand=$(ssh_node "$ip" 'apt-cache policy proxmox-kernel-7.0 2>/dev/null | grep -m1 Candidate | sed "s/.*: //"')
  idx=$(ssh_node "$ip" 'stat -c %y /var/lib/apt/lists 2>/dev/null | cut -d: -f1-2')

  printf '%s|%s|%s|%s|%s\n' "$name" "$run" "$inst" "${cand:-?}" "${idx:-?}" >> "$TMP"
done

echo
printf '%-15s %-22s %-12s %-12s %s\n' NODE RUNNING INSTALLED CANDIDATE INDEX-REFRESHED
while IFS='|' read -r name run inst cand idx; do
  printf '%-15s %-22s %-12s %-12s %s\n' "$name" "$run" "$inst" "$cand" "$idx"
done < "$TMP"
echo

uniq_running=$(cut -d'|' -f2 "$TMP" | sort -u | wc -l | tr -d ' ')
uniq_installed=$(cut -d'|' -f3 "$TMP" | sort -u | wc -l | tr -d ' ')
uniq_candidate=$(cut -d'|' -f4 "$TMP" | sort -u | wc -l | tr -d ' ')

if [ "$uniq_running" -ne 1 ] || [ "$uniq_installed" -ne 1 ]; then
  echo "DRIFT: ${uniq_running} distinct running kernel(s), ${uniq_installed} distinct installed version(s)"
  fail=1
else
  echo "PARITY: all $(wc -l < "$TMP" | tr -d ' ') nodes run and have installed $(cut -d'|' -f3 "$TMP" | head -1)"
fi

if [ "$uniq_candidate" -ne 1 ]; then
  echo "WARNING: upgrade candidates differ (${uniq_candidate} distinct)"
  echo "         Do NOT run a rolling dist-upgrade until every node sees the same candidate."
  fail=1
fi

exit "$fail"
