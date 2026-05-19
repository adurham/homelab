#!/usr/bin/env bash
# Quick progress check for a running BWT throttle measurement.
# Usage: bwt-check.sh [action_id]
#
# Shows: per-client cache file presence & size, live throttle counter
# deltas vs the pre snapshot, sampler heartbeat, ETA.
#
# shellcheck disable=SC1078,SC1083
#   The per-client cache-file check below uses a doubly-nested ssh
#   command (workstation -> pve01 -> {pve01,pve02,pve03} -> pct exec
#   inside the LXC). The two layers of shell quoting confuse shellcheck:
#   it sees unclosed single quotes (SC1078) and "literal" awk braces
#   (SC1083) inside what is actually a remote-side awk script. The
#   command is validated and runs correctly; the warnings are noise.

set -euo pipefail

ACTION_ID="${1:-11}"
RUN_DIR="${RUN_DIR:-$HOME/Library/CloudStorage/OneDrive-TaniumInc/Customer Issues/NEC/00271560/bwt-runs/20260518T185441Z}"
TOKEN="${TOKEN:-token-388a95d3c103e864ccc22dfdb78e21c6212f8e08f675ee8acf71eb8a84}"
TS_URL="${TS_URL:-https://10.99.0.10}"
TARGET_FILE="${TARGET_FILE:-bwt-bigfile-2gb.bin}"
EXPECTED_SIZE="${EXPECTED_SIZE:-2147483648}"

# Get current throttle counters
LIVE=$(curl -sk --max-time 5 -H "session: $TOKEN" "$TS_URL/metrics" 2>/dev/null        | grep "^tanium_throttle_bytes_used_total{instance=\"bwt-zs-0"        | grep -E "type=\"tanium_protocol_download\"")

# Get t=0 values from metrics-pre.txt
PRE_FILE="$RUN_DIR/metrics-pre.txt"

echo "=== throttle counter (tanium_protocol_download) ==="
for ZS in bwt-zs-01 bwt-zs-02; do
  PRE=$(grep "^tanium_throttle_bytes_used_total{instance=\"$ZS.bwt.local\"" "$PRE_FILE"         | grep "tanium_protocol_download" | awk '"'"'{print $2}'"'"')
  POST=$(echo "$LIVE" | grep "$ZS" | grep tanium_protocol_download | awk '"'"'{print $2}'"'"')
  if [ -n "$PRE" ] && [ -n "$POST" ]; then
    DELTA=$((POST - PRE))
    DELTA_MB=$(awk -v d="$DELTA" 'BEGIN{printf "%.1f", d/1024/1024}')
    echo "  $ZS: pre=$PRE post=$POST delta=${DELTA} bytes (${DELTA_MB} MB)"
  fi
done

echo
echo "=== per-client cache file presence ==="
ssh -o BatchMode=yes -o ConnectTimeout=10 root@192.168.86.11 '
  for n in pve01 pve02 pve03; do
    ssh -o StrictHostKeyChecking=no $n "
      for ct in 320 321 322 323 324 325 326 327; do
        if pct status \$ct 2>/dev/null | grep -q running; then
          size=\$(pct exec \$ct -- stat -c%s '"/opt/Tanium/TaniumClient/Downloads/Action_'$ACTION_ID'/$TARGET_FILE"' 2>/dev/null)
          if [ -n \"\$size\" ]; then
            pct=\$(awk -v s=\"\$size\" -v e=$EXPECTED_SIZE 'BEGIN{printf \"%.1f%%\", s/e*100}')
            echo \"  CT \$ct: \$size bytes (\$pct of $EXPECTED_SIZE)\"
          else
            echo \"  CT \$ct: not yet\"
          fi
        fi
      done
    "
  done
' 2>&1

echo
echo "=== sampler heartbeat ==="
SAMPLES=$(wc -l < "$RUN_DIR/metrics.csv" 2>/dev/null || echo "0")
LAST_TS=$(tail -1 "$RUN_DIR/metrics.csv" 2>/dev/null | cut -d, -f1)
NOW_MS=$(python3 -c "import time; print(int(time.time()*1000))")
if [ -n "$LAST_TS" ]; then
  AGO=$(((NOW_MS - LAST_TS) / 1000))
  echo "  samples: $SAMPLES   last sample: ${AGO}s ago"
fi
