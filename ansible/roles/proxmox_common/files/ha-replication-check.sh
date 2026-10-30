#!/usr/bin/env bash
# ha-replication-check.sh -- find HA-managed guests that have NO replication job.
#
# Why this exists (owner's rule, 2026-10-30): every VM or CT with HA set NEEDS a
# replication job. The cluster has no shared storage; a guest's disks live on one
# node's local pool, and pvesr is what puts a usable copy on another node. An HA
# service without a replication job can still be relocated by the CRM after a
# fence -- and then it lands on a node that has no disk for it and refuses to
# start. That is exactly how ct:105 (ntp-01) broke on 2026-10-30: its disks were
# on pve03's local pool, a fence relocated the service to pve02, and the start
# failed with "dataset does not exist" while the container sat stopped.
#
# Nothing about that state is visible in Proxmox's own metrics: the HA config and
# the replication config simply disagree, and both look fine on their own.
#
# Every run (systemd timer, every 5 minutes) on each pve node:
#   1. HA-managed guests: /etc/pve/ha/resources.cfg via
#      `pvesh get /cluster/ha/resources` (sid = ct:105 / vm:241, plus its state).
#      Services explicitly `disabled` are skipped: a disabled service is not
#      relocated, and flagging it would be noise.
#   2. Guests with a replication job: `pvesh get /cluster/replication`
#      (job id 105-0, guest 105).
#   3. Any guest in (1) but not (2) is reported twice:
#        journal: HA-NO-REPLICATION vmid=<n> kind=<ct|vm> node=<node>
#        metric : ha_guest_without_replication{node="pveNN",vmid="NNN",kind="ct"} 1
#
# FAIL-OPEN, deliberately: if either listing fails (pmxcfs not up yet, for
# instance) the whole comparison is SKIPPED rather than treating an empty list as
# truth -- otherwise a transient failure would report every guest as unprotected,
# and a check that cries wolf on every boot is worse than no check. The metric
# set always carries ha_replication_check_ok so a skipped scan is itself alertable.
#
# Managed by ansible: roles/proxmox_common.

set -uo pipefail

TEXTFILE_DIR="${TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
NODE="${NODE:-$(hostname -s)}"
OUT_FILE="${TEXTFILE_DIR}/ha_replication.prom"
LOG_TAG="ha-replication"

log() {
  # $1 = message, $2 = priority (defaults to daemon.info)
  logger -t "$LOG_TAG" -p "${2:-daemon.info}" "$1"
}

if [ "$(id -u)" -ne 0 ]; then
  log "must run as root (pvesh on /cluster needs it); no scan performed" daemon.err
  exit 1
fi

if ! mkdir -p "$TEXTFILE_DIR"; then
  log "cannot create textfile dir ${TEXTFILE_DIR}; no scan performed" daemon.err
  exit 1
fi

tmp_file="$(mktemp "${TEXTFILE_DIR}/.ha_replication.XXXXXX")" || {
  log "cannot create a temp file in ${TEXTFILE_DIR}; no scan performed" daemon.err
  exit 1
}
trap 'rm -f "$tmp_file"' EXIT

scan_ok=1
ha_json=""
repl_json=""

if ! ha_json="$(pvesh get /cluster/ha/resources --output-format json 2>/dev/null)"; then
  scan_ok=0
  log "pvesh get /cluster/ha/resources failed -- scan SKIPPED on ${NODE}" daemon.err
fi

if ! repl_json="$(pvesh get /cluster/replication --output-format json 2>/dev/null)"; then
  scan_ok=0
  log "pvesh get /cluster/replication failed -- scan SKIPPED on ${NODE}" daemon.err
fi

uncovered_series=()
uncovered_count=0

if [ "$scan_ok" -eq 1 ]; then
  while read -r sid state; do
    [ -n "$sid" ] || continue
    # sid is "ct:105" or "vm:241"; a disabled service is not relocated, so it is
    # not this check's business.
    [ "$state" = "disabled" ] && continue
    vmid="${sid#*:}"
    kind="${sid%%:*}"
    case "$vmid" in
      ''|*[!0-9]*) continue ;;
    esac
    [ "$kind" = "ct" ] || [ "$kind" = "vm" ] || continue
    # covered if any replication job references this guest
    if printf '%s\n' "$repl_json" | grep -q "\"guest\": *${vmid}[,}]"; then
      continue
    fi
    uncovered_count=$((uncovered_count + 1))
    uncovered_series+=("ha_guest_without_replication{node=\"${NODE}\",vmid=\"${vmid}\",kind=\"${kind}\"} 1")
    log "HA-NO-REPLICATION vmid=${vmid} kind=${kind} node=${NODE}" daemon.warning
  done < <(printf '%s\n' "$ha_json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for entry in data or []:
    sid = entry.get("sid") or ""
    state = entry.get("state") or ""
    if sid:
        print(sid, state)
')
fi

{
  printf '# HELP ha_guest_without_replication HA-managed guest with no pvesr replication job: after a fence it can be relocated to a node that has no disk for it and will not start.\n'
  printf '# TYPE ha_guest_without_replication gauge\n'
  if [ "${#uncovered_series[@]}" -gt 0 ]; then
    printf '%s\n' "${uncovered_series[@]}"
  fi
  printf '# HELP ha_replication_check_ok 1 when both cluster listings succeeded, 0 when the scan was skipped.\n'
  printf '# TYPE ha_replication_check_ok gauge\n'
  printf 'ha_replication_check_ok{node="%s"} %s\n' "$NODE" "$scan_ok"
  printf '# HELP ha_replication_check_timestamp_seconds Unix time of the last completed HA/replication scan on this node.\n'
  printf '# TYPE ha_replication_check_timestamp_seconds gauge\n'
  printf 'ha_replication_check_timestamp_seconds{node="%s"} %s\n' "$NODE" "$(date +%s)"
} > "$tmp_file" || {
  log "cannot write ${tmp_file}" daemon.err
  exit 1
}

# 0644 (not mktemp's 0600) so the exporter's collector can read it, then rename
# into place: node_exporter/Alloy never sees a half-written file.
chmod 0644 "$tmp_file" || exit 1
mv -f "$tmp_file" "$OUT_FILE" || {
  log "cannot move ${tmp_file} into ${OUT_FILE}" daemon.err
  exit 1
}

if [ "$uncovered_count" -gt 0 ]; then
  log "${uncovered_count} HA-managed guest(s) without a replication job -- add a pvesr job (two targets, rate 15) or the next relocation will strand them" daemon.warning
fi

exit 0
