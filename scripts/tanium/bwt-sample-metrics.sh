#!/usr/bin/env bash
# Long-running /metrics sampler for the BWT throttle measurement rig.
# Run as: ./sample-ts-metrics.sh <ts_url> <token> <outpath> <interval>
#
# We're a separate background process so the orchestrator can return
# control to the shell immediately — this is the workaround for the
# CLI environment's 180s foreground timeout limit. Stop by SIGTERM
# or by killing the PID.

set -euo pipefail

TS_URL="${1:?usage: sample-ts-metrics.sh <ts_url> <token> <outpath> <interval>}"
TOKEN="${2:?missing token}"
OUTPATH="${3:?missing outpath}"
INTERVAL="${4:-1}"

# Patterns we keep — same as the python orchestrator. Filter at the
# source to keep the CSV small (24 hr × 86400s × ~30 metrics × 200
# bytes = ~70 GB without filtering).
PATTERN='^(tanium_throttle_bytes_used_total|tanium_client_external_download_bytes_read_total|tanium_throttle_writes_total|tanium_chunk_request_queue_dropped_total|tanium_client_connection_count)\b'

# CSV header — only write if file is empty/new.
if [ ! -s "$OUTPATH" ]; then
  echo "epoch_ms_local,metric_line" > "$OUTPATH"
fi

while true; do
  ts="$(python3 -c 'import time; print(int(time.time()*1000))')"
  curl -sk --max-time "$INTERVAL" -H "session: $TOKEN" "$TS_URL/metrics" 2>/dev/null \
    | grep -E "$PATTERN" \
    | sed "s/^/${ts},/" >> "$OUTPATH" || true
  sleep "$INTERVAL"
done
