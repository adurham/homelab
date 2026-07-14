#!/usr/bin/env bash
# tailscale-gw-rejoin.sh — re-enroll tailscale-gw (CT 101) into the tailnet.
#
# BREAK-GLASS ONLY as of 2026-07-14: tailscale-gw's node-key expiry is now
# DISABLED (via POST /api/v2/device/{id}/key {"keyExpiryDisabled":true}), so it
# no longer falls out of the tailnet on a 180-day schedule. This script is kept
# for non-expiry enrollment corruption (coordination-server drop, corrupted
# state, manual `tailscale logout`, etc.) — symptoms: gallery.chi and other
# chi.lab.amd-e.com hosts stop resolving from the Mac; SSH to 172.16.0.x times
# out; `tailscale status` inside CT 101 shows "Logged out".
#
# Flow:
#   1. Read Tailscale API token from macOS keychain (TailscaleAPIToken).
#   2. Generate a single-use auth key via the Tailscale API (POST /tailnet/-/keys).
#   3. Locate the PVE node hosting CT 101 (it can HA-migrate between pve01/02/03).
#   4. `pct exec 101 -- tailscale up --authkey=... --advertise-routes=172.16.0.0/24
#      --hostname=tailscale-gw --snat-subnet-routes=false --reset` inside the CT.
#   5. Verify: tailscale status shows the node online + Mac can ping 172.16.0.10 (dns-01).
#
# The API token expires every 90 days (Tailscale max). Since this script is now
# break-glass only, token rotation is low-priority (not outage-critical). To
# rotate: generate a new token at https://login.tailscale.com/admin/settings/keys
# and update all three stores (keychain TailscaleAPIToken, homelab vault
# vault_tailscale_api_token, 1Password "Tailscale API Token" item). A reminder
# cron fires 2026-10-05 (a week before the 2026-10-12 expiry).
#
# Exit codes: 0 = re-enrolled + verified, 1 = failure (see output).

set -euo pipefail

CT_ID=101
TAILSCALE_IP=100.86.168.35
ADVERTISE_ROUTES="172.16.0.0/24"
HOSTNAME_TS="tailscale-gw"
KEYCHAIN_SERVICE="TailscaleAPIToken"
KEYCHAIN_ACCT="adam.durham"

log() { printf "  %s\n" "$*"; }
err() { printf "  [ERROR] %s\n" "$*" >&2; }

# ── 1. API token from keychain ──────────────────────────────────────────────
log "reading API token from keychain ($KEYCHAIN_SERVICE)..."
TOKEN=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$KEYCHAIN_ACCT" -w 2>/dev/null) || {
  err "API token not found in keychain. Store it with: security add-generic-password -s $KEYCHAIN_SERVICE -a $KEYCHAIN_ACCT -w '<token>' -U"
  exit 1
}
[ -n "$TOKEN" ] || { err "keychain returned empty token"; exit 1; }
log "token retrieved (len=${#TOKEN})"

# ── 2. generate single-use auth key via API ──────────────────────────────────
log "generating single-use auth key via Tailscale API..."
AUTHKEY=$(curl -sS --max-time 15 -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"capabilities":{"devices":{"create":{"reusable":false,"ephemeral":false,"preauthorized":true}}},"expirySeconds":600,"description":"tailscale-gw-rejoin auto"}' \
  https://api.tailscale.com/api/v2/tailnet/-/keys 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('key',''))" 2>/dev/null) || true
if [ -z "$AUTHKEY" ]; then
  err "API key generation failed. Check token validity (expires 2026-10-12) and network."
  exit 1
fi
log "auth key generated (single-use, 10min TTL)"

# ── 3. find the PVE node hosting CT 101 ─────────────────────────────────────
log "locating hosting node for CT $CT_ID..."
NODE=$(ssh -o ConnectTimeout=10 root@192.168.86.11 \
  "pvesh get /cluster/resources --type vm --output-format json 2>/dev/null" 2>/dev/null | \
  python3 -c "import json,sys; r=[x for x in json.load(sys.stdin) if x['vmid']==$CT_ID]; print(r[0]['node'] if r else '')" 2>/dev/null) || true
[ -n "$NODE" ] || { err "could not locate CT $CT_ID in cluster"; exit 1; }
case "$NODE" in
  pve01) NODE_IP=192.168.86.11 ;;
  pve02) NODE_IP=192.168.86.12 ;;
  pve03) NODE_IP=192.168.86.13 ;;
  *)     NODE_IP=192.168.86.13 ;;
esac
log "CT $CT_ID is on $NODE ($NODE_IP)"

# ── 4. tailscale up inside the CT ───────────────────────────────────────────
log "running tailscale up inside CT $CT_ID..."
OUT=$(ssh -o ConnectTimeout=15 root@$NODE_IP "pct exec $CT_ID -- tailscale up --reset --authkey=$AUTHKEY --advertise-routes=$ADVERTISE_ROUTES --accept-routes=false --hostname=$HOSTNAME_TS --snat-subnet-routes=false" 2>&1) || true
echo "$OUT" | grep -iE "error|success|logged" | head -3 || log "(no error output — likely success)"

# ── 5. verify ───────────────────────────────────────────────────────────────
sleep 2
log "verifying tailscale-gw is back..."
STATE=$(ssh -o ConnectTimeout=10 root@$NODE_IP "pct exec $CT_ID -- tailscale status" 2>&1 | head -1)
log "  tailscale status: $STATE"

log "checking Mac can reach dns-01 (172.16.0.10)..."
if ping -c2 -t3 172.16.0.10 >/dev/null 2>&1; then
  log "OK — 172.16.0.0/24 subnet route is back. gallery.chi should resolve now."
  exit 0
else
  err "dns-01 (172.16.0.10) still unreachable. Check tailscale status on the CT: ssh root@$NODE_IP 'pct exec $CT_ID -- tailscale status'"
  exit 1
fi