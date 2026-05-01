#!/usr/bin/env bash
# Thin curl wrapper that injects the JWT token saved by grafana_auth.py.
# README_GRAFANA_AUTH.md references this; the script was missing.
#
# Usage:
#   ./grafana_curl.sh https://grafana.example.com/api/dashboards/home
#   ./grafana_curl.sh -X POST https://... -d @body.json
#
# Override TOKEN_FILE if your token isn't at the default path:
#   TOKEN_FILE=/tmp/other.token ./grafana_curl.sh ...

set -euo pipefail

TOKEN_FILE="${TOKEN_FILE:-grafana_token.txt}"

if [ ! -r "$TOKEN_FILE" ]; then
    echo "error: token file '$TOKEN_FILE' not readable. run grafana_auth.py first." >&2
    exit 1
fi

token="$(cat "$TOKEN_FILE")"
exec curl -H "Authorization: Bearer $token" "$@"
