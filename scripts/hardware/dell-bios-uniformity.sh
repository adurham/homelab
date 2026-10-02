#!/usr/bin/env bash
# dell-bios-uniformity.sh — audit and apply a uniform, homelab-appropriate Dell
# BIOS configuration on the pve nodes via dell-wmi-sysman (sysfs).
#
# WHY
#   The fleet drifted apart (pve01 = OptiPlex 7090, pve02/03 = 5080 Micro).
#   Most differences are just hardware — but a few matter on a headless
#   hypervisor:
#     * Deep Sleep cuts NIC power in S4/S5, which disables Wake-on-LAN.
#     * SMART error reporting HALTS POST on a failing disk ("Strike F1").
#       These boxes have no keyboard and sit in a basement, so a halted POST
#       is an unreachable node — and it would also block AC-Recovery boot.
#       Disk health is already tracked properly by roles/smartctl_exporter ->
#       VictoriaMetrics -> Grafana, so POST-level SMART is pure downside.
#     * Absolute/Computrace is a corporate asset-tracking agent.
#     * BIOSConnect / SupportAssist are vendor cloud/recovery hooks.
#
# USAGE
#   dell-bios-uniformity.sh                    # dry run (default): show, change nothing
#   sudo dell-bios-uniformity.sh --apply       # apply; prompts for BIOS admin password
#   sudo dell-bios-uniformity.sh --apply -y    # apply without the confirm prompt
#   dell-bios-uniformity.sh --attr DeepSleepCtrl   # single attribute (dry or --apply)
#
# The BIOS admin password IS required for writes: dell-wmi-sysman refuses
# attribute writes without it (dmesg: "admin password must be configured").
# It is read silently, held only in the kernel's per-session buffer, and
# cleared on every exit path. It never touches disk, argv, or the environment.

set -uo pipefail

BASE="/sys/class/firmware-attributes/dell-wmi-sysman"
ATTRS="$BASE/attributes"
AUTH="$BASE/authentication/Admin/current_password"
NODE="$(hostname -s 2>/dev/null || hostname)"

APPLY=0
ASSUME_YES=0
ONLY=""

usage() {
  sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)   APPLY=1 ;;
    -y|--yes)  ASSUME_YES=1 ;;
    --attr)    ONLY="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ ! -d "$ATTRS" ]; then
  echo "ERROR: $ATTRS not found — not a Dell system, or dell-wmi-sysman is not loaded." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Desired-state table:  "<target>|<fallback>...|<human reason>"
# The first target present in the attribute's possible_values wins, so the
# same table covers both the 7090 and the 5080 (their enum labels differ).
# Never add "PermanentlyDisabled" here — that state is one-way.
# ---------------------------------------------------------------------------
declare -A DESIRE=(
  [AcPwrRcvry]="On|boot automatically after AC loss (set 2026-10-01; idempotent check)"
  [DeepSleepCtrl]="Disabled|deep sleep cuts NIC power in S4/S5 and breaks Wake-on-LAN"
  [WakeOnLan]="LanOnly|only remote power-on path available for a headless node"
  [SmartErrors]="Disabled|SMART reporting HALTS POST on a failing disk (F1 prompt, no keyboard). Disk health is tracked by smartctl_exporter -> Grafana instead"
  [Absolute]="DisableAbsolute|Disabled|corporate asset-tracking agent (Computrace/Absolute)"
  [BIOSConnect]="Disabled|vendor cloud hook"
  [SupportAssistOSRecovery]="Disabled|vendor recovery agent; not wanted on a hypervisor"
  [AutoOSRecoveryThreshold]="OFF|only meaningful alongside SupportAssistOSRecovery"
  [Microphone]="Disabled|headless box in a basement"
  [InternalSpeaker]="Disabled|headless; beep codes need someone physically present anyway"
  [UsbPowerShare]="Disabled|keeps USB ports powered while the box is off"
  [PrimaryVideoSlot]="Auto|inert on a headless box; align all three (pve02 was Onboard)"
)

# States that already count as correct even though they differ from the
# target label (Absolute=PermanentlyDisabled is more final than Disabled).
declare -A EXTRA_OK=(
  [Absolute]="PermanentlyDisabled"
)

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

token_in_list() {  # $1 needle, $2 ';'-separated list
  local needle t oldifs="$IFS"
  needle="$(lower "$1")"
  IFS=';'
  for t in $2; do
    if [ -n "$t" ] && [ "$(lower "$t")" = "$needle" ]; then
      IFS="$oldifs"; return 0
    fi
  done
  IFS="$oldifs"
  return 1
}

pick_target() {  # $1 '|'-separated preference list, $2 possible_values
  local p oldifs="$IFS"
  IFS='|'
  for p in $1; do
    if token_in_list "$p" "$2"; then
      IFS="$oldifs"; printf '%s' "$p"; return 0
    fi
  done
  IFS="$oldifs"
  return 1
}

ROWS=()
collect() {
  local attr spec targets reason dir cur poss target extra

  for attr in $(printf '%s\n' "${!DESIRE[@]}" | sort); do
    if [ -n "$ONLY" ] && [ "$attr" != "$ONLY" ]; then continue; fi
    spec="${DESIRE[$attr]}"
    targets="${spec%|*}"
    reason="${spec##*|}"
    dir="$ATTRS/$attr"

    if [ ! -d "$dir" ]; then
      ROWS+=("ABSENT|$attr|-|(n/a)|$reason (absent on this model)")
      continue
    fi

    cur="$(cat "$dir/current_value" 2>/dev/null || true)"
    poss="$(tr -d '\n' < "$dir/possible_values" 2>/dev/null || true)"

    if ! target="$(pick_target "$targets" "$poss")"; then
      # NOTE: $targets is itself '|'-separated, and ROWS entries are parsed
      # with IFS='|' — so render the preference list with commas here to
      # keep the field count intact.
      ROWS+=("UNSUPPORTED|$attr|$cur|(none)|no target value available (wanted: ${targets//|/,}) (possible: $poss)")
      continue
    fi

    if [ "$(lower "$cur")" = "$(lower "$target")" ]; then
      ROWS+=("MATCH|$attr|$cur|$target|$reason")
      continue
    fi

    extra="${EXTRA_OK[$attr]:-}"
    if [ -n "$extra" ] && token_in_list "$cur" "$extra"; then
      ROWS+=("MATCH+|$attr|$cur|$target|already in a more-restrictive state than '$target'")
      continue
    fi

    ROWS+=("DIFF|$attr|$cur|$target|$reason")
  done
}

print_report() {
  local r status attr cur target reason n_match=0 n_diff=0 n_other=0

  printf 'node: %s\n\n' "$NODE"
  printf '%-27s %-18s %-18s %s\n' "ATTR" "CURRENT" "TARGET" "STATUS"
  printf '%-27s %-18s %-18s %s\n' "---------------------------" "------------------" "------------------" "------"
  for r in "${ROWS[@]}"; do
    IFS='|' read -r status attr cur target reason <<< "$r"
    printf '%-27s %-18s %-18s %s\n' "$attr" "$cur" "$target" "$status"
    case "$status" in
      MATCH|MATCH+) n_match=$((n_match+1)) ;;
      DIFF)         n_diff=$((n_diff+1)) ;;
      *)            n_other=$((n_other+1)) ;;
    esac
  done
  printf '\nsummary: %d already correct, %d to change, %d needing attention\n' \
    "$n_match" "$n_diff" "$n_other"

  if [ "$n_diff" -gt 0 ] || [ "$n_other" -gt 0 ]; then
    printf '\nnotes:\n'
    for r in "${ROWS[@]}"; do
      IFS='|' read -r status attr cur target reason <<< "$r"
      case "$status" in
        MATCH|MATCH+) ;;
        DIFF) printf '  [change]  %-25s %s -> %s\n            %s\n' "$attr" "$cur" "$target" "$reason" ;;
        *)    printf '  [%s] %-25s %s\n            %s\n' "$(lower "$status")" "$attr" "$cur" "$reason" ;;
      esac
    done
  fi
}

cleanup() {
  # A single newline clears the kernel's session password buffer; a
  # zero-byte write is rejected (the attribute validates length).
  if [ "${PRIMED:-0}" -eq 1 ]; then
    printf '\n' > "$AUTH" 2>/dev/null || true
    PRIMED=0
  fi
  unset PW 2>/dev/null || true
}
trap cleanup EXIT

collect

if [ -n "$ONLY" ] && [ "${#ROWS[@]}" -eq 0 ]; then
  echo "ERROR: '$ONLY' is not in the desired-state table." >&2
  exit 2
fi

print_report

if [ "$APPLY" -eq 0 ]; then
  printf '\n(dry run — nothing was written. To apply, re-run with --apply; it will prompt for the BIOS admin password.)\n'
  exit 0
fi

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: --apply requires root." >&2
  exit 1
fi

CHANGES=()
for r in "${ROWS[@]}"; do
  IFS='|' read -r status attr cur target reason <<< "$r"
  if [ "$status" = "DIFF" ]; then
    CHANGES+=("$attr|$cur|$target")
  fi
done

if [ "${#CHANGES[@]}" -eq 0 ]; then
  printf '\nnothing to change on %s.\n' "$NODE"
  exit 0
fi

printf '\nplanned changes on %s:\n' "$NODE"
for c in "${CHANGES[@]}"; do
  IFS='|' read -r attr cur target <<< "$c"
  printf '  %-27s %s -> %s\n' "$attr" "$cur" "$target"
done

if [ "$ASSUME_YES" -ne 1 ]; then
  printf '\napply %d change(s)? [y/N] ' "${#CHANGES[@]}"
  read -r ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *) echo "aborted."; exit 0 ;;
  esac
fi

if [ ! -e "$AUTH" ]; then
  echo "ERROR: $AUTH missing — cannot supply credentials." >&2
  exit 1
fi

printf 'BIOS admin password: '
read -r -s PW
echo

if ! printf '%s' "$PW" > "$AUTH" 2>/dev/null; then
  echo "ERROR: could not prime the credential buffer." >&2
  unset PW
  exit 1
fi
PRIMED=1
unset PW

FAILED=0
printf '\napplying:\n'
for c in "${CHANGES[@]}"; do
  IFS='|' read -r attr cur target <<< "$c"
  errfile="$(mktemp /run/dell-bios-uniformity.XXXXXX.err)"
  if printf '%s' "$target" > "$ATTRS/$attr/current_value" 2>"$errfile"; then
    sleep 1
    new="$(cat "$ATTRS/$attr/current_value" 2>/dev/null || true)"
    if [ "$(lower "$new")" = "$(lower "$target")" ]; then
      printf '  OK       %-27s %s -> %s\n' "$attr" "$cur" "$new"
    else
      printf '  FAILED   %-27s wrote "%s" but read "%s" back\n' "$attr" "$target" "$new"
      printf '           check: dmesg | tail\n'
      FAILED=$((FAILED+1))
    fi
  else
    printf '  FAILED   %-27s write rejected: %s\n' "$attr" "$(cat "$errfile" 2>/dev/null)"
    dmesg 2>/dev/null | tail -2 | sed 's/^/           /'
    FAILED=$((FAILED+1))
  fi
  rm -f "$errfile"
done

printf '\nfinal state on %s:\n' "$NODE"
ROWS=()
collect
print_report

if [ "$FAILED" -gt 0 ]; then
  printf '\n%d change(s) failed — see above.\n' "$FAILED" >&2
  exit 1
fi
printf '\nall changes applied.\n'
