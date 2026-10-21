#!/usr/bin/env bash
# orphan-guest-check.sh -- find Proxmox guests that are running outside
# Proxmox's management.
#
# The 2026-10-21 incident this closes: two unmanaged duplicate guests were
# found running on the cluster and NOTHING alerted.
#   1. One container ran on TWO nodes at once, same MACs and IPs, for 22
#      hours (split brain).
#   2. VM 'ts-01' ran on pve01, which has no config for it, while the real
#      ts-01 ran on pve02 for 8 days (its NIC counters sat at zero).
# In both cases the node hosting the extra process had no idea: `pct list` /
# `qm list` only report guests registered in THAT node's config. A stale
# lxc-start or /usr/bin/kvm left behind by an interrupted migration, a
# hand-started copy, or a duplicated root filesystem keeps running happily and
# Proxmox never shows it anywhere.
#
# Every run (systemd timer, every 5 minutes):
#   1. VMIDs this node actually manages: first column of `pct list` / `qm list`.
#   2. VMIDs with a live guest process on this node:
#        container -> /usr/bin/lxc-start -F -n <vmid>
#        VM        -> /usr/bin/kvm -id <vmid>
#   3. Every process VMID that is missing from the managed list is reported
#      twice:
#        journal: ORPHAN-GUEST vmid=<n> kind=<ct|vm> node=<node>
#        metric : orphan_guests{node="pveNN",vmid="NNN",kind="ct"} 1
#
# The metric goes to the textfile directory Alloy's node_exporter-style
# collector already scrapes on these nodes, because Proxmox's own metrics can
# never describe a guest it does not manage.
#
# FAIL-OPEN, deliberately: if `pct list` or `qm list` fails (pmxcfs not up yet,
# for instance), that half of the scan is SKIPPED rather than treating "the
# managed list is empty" as truth -- otherwise every running guest on the node
# would be reported as an orphan at once. The skip is exported as
# orphan_guests_scan_ok 0, so a broken scan is visible without paging.
#
# Managed by ansible: roles/proxmox_common.

set -uo pipefail

TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
NODE="${NODE:-$(hostname -s)}"
OUT_FILE="${TEXTFILE_DIR}/orphan_guests.prom"
LOG_TAG="orphan-guest"

log() {
  # $1 = message, $2 = priority (defaults to daemon.info)
  logger -t "$LOG_TAG" -p "${2:-daemon.info}" "$1"
}

if [ "$(id -u)" -ne 0 ]; then
  log "must run as root (pct/qm need root); no scan performed" daemon.err
  exit 1
fi

if ! mkdir -p "$TEXTFILE_DIR"; then
  log "cannot create textfile dir ${TEXTFILE_DIR}; no scan performed" daemon.err
  exit 1
fi

tmp_file="$(mktemp "${TEXTFILE_DIR}/.orphan_guests.XXXXXX")" || {
  log "cannot create a temp file in ${TEXTFILE_DIR}; no scan performed" daemon.err
  exit 1
}
trap 'rm -f "$tmp_file"' EXIT

scan_ok=1
ct_ok=1
vm_ok=1
managed_ct=""
managed_vm=""

if ct_raw="$(pct list 2>/dev/null)"; then
  managed_ct="$(printf '%s\n' "$ct_raw" | awk 'NR > 1 && $1 ~ /^[0-9]+$/ { print $1 }')"
else
  ct_ok=0
  scan_ok=0
  log "pct list failed -- container half of the orphan scan SKIPPED on ${NODE}" daemon.err
fi

if vm_raw="$(qm list 2>/dev/null)"; then
  managed_vm="$(printf '%s\n' "$vm_raw" | awk 'NR > 1 && $1 ~ /^[0-9]+$/ { print $1 }')"
else
  vm_ok=0
  scan_ok=0
  log "qm list failed -- VM half of the orphan scan SKIPPED on ${NODE}" daemon.err
fi

# Print the VMIDs of guest processes on this node whose argv[0] basename is
# $1 (lxc-start / kvm) and which carry `$2 <vmid>` ($3 = -n / -id).
guest_vmids() {
  ps -eww -o args= | awk -v want="$1" -v flag="$2" '
    {
      cmd = $1
      sub(/.*\//, "", cmd)
      if (cmd != want) next
      # standalone flag token only: -object iothread,id=x and -device id=y
      # must not be mistaken for kvm'"'"'s own -id <vmid>
      for (i = 2; i < NF; i++) {
        if ($i == flag && $(i + 1) ~ /^[0-9]+$/) { print $(i + 1); break }
      }
    }' | sort -u
}

is_managed() {
  # $1 = newline-separated managed VMIDs, $2 = candidate VMID
  printf '%s\n' "$1" | awk -v id="$2" '$1 == id { found = 1 } END { exit found ? 0 : 1 }'
}

orphan_series=()
orphan_count=0

if [ "$ct_ok" -eq 1 ]; then
  while read -r vmid; do
    [ -n "$vmid" ] || continue
    is_managed "$managed_ct" "$vmid" && continue
    orphan_count=$((orphan_count + 1))
    orphan_series+=("orphan_guests{node=\"${NODE}\",vmid=\"${vmid}\",kind=\"ct\"} 1")
    log "ORPHAN-GUEST vmid=${vmid} kind=ct node=${NODE}" daemon.warning
  done < <(guest_vmids lxc-start -n)
fi

if [ "$vm_ok" -eq 1 ]; then
  while read -r vmid; do
    [ -n "$vmid" ] || continue
    is_managed "$managed_vm" "$vmid" && continue
    orphan_count=$((orphan_count + 1))
    orphan_series+=("orphan_guests{node=\"${NODE}\",vmid=\"${vmid}\",kind=\"vm\"} 1")
    log "ORPHAN-GUEST vmid=${vmid} kind=vm node=${NODE}" daemon.warning
  done < <(guest_vmids kvm -id)
fi

{
  printf '# HELP orphan_guests Guest process (lxc-start/kvm) running for a VMID this node does not manage: a duplicate/split-brain guest.\n'
  printf '# TYPE orphan_guests gauge\n'
  if [ "${#orphan_series[@]}" -gt 0 ]; then
    printf '%s\n' "${orphan_series[@]}"
  fi
  printf '# HELP orphan_guests_scan_ok 1 when pct and qm listing both succeeded, 0 when half of the scan was skipped.\n'
  printf '# TYPE orphan_guests_scan_ok gauge\n'
  printf 'orphan_guests_scan_ok{node="%s"} %s\n' "$NODE" "$scan_ok"
  printf '# HELP orphan_guests_scan_timestamp_seconds Unix time of the last completed orphan scan on this node.\n'
  printf '# TYPE orphan_guests_scan_timestamp_seconds gauge\n'
  printf 'orphan_guests_scan_timestamp_seconds{node="%s"} %s\n' "$NODE" "$(date +%s)"
} > "$tmp_file" || {
  log "cannot write ${tmp_file}" daemon.err
  exit 1
}

# 0644 (not mktemp's 0600) so the exporter's collector can read it, then
# rename into place: node_exporter/Alloy never sees a half-written file.
chmod 0644 "$tmp_file" || exit 1
mv -f "$tmp_file" "$OUT_FILE" || {
  log "cannot move ${tmp_file} into ${OUT_FILE}" daemon.err
  exit 1
}

if [ "$orphan_count" -gt 0 ]; then
  log "${orphan_count} orphan guest process(es) on ${NODE} -- compare pct/qm list with the process table" daemon.warning
fi

exit 0
