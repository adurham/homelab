#!/bin/bash
# Deploy + byte-verify the overnight pre-cool feature to the live house.
#
# WHY THIS SCRIPT EXISTS: the deploy is blocked ONLY on SSH auth. The key
# ("Personal Macbook" RSA) lives in the 1Password SSH agent, which returned
# "agent refused operation" / "communication with agent failed" to the
# background agent session — it needs an interactive unlock/biometric
# approval that a non-interactive session cannot trigger. The HA server
# ACCEPTS the key ("debug1: Server accepts key ..."), so this is purely a
# local signing-authorization wall, not a server/permissions problem.
#
# RUN THIS in a normal interactive terminal (unlock 1Password first, and
# approve the prompt if one appears). Everything else is already done:
# commit 2b540a2 is pushed to origin/main and all 16 suites are green.
set -u

APP=/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps/smart_vent_controller.py
REMOTE=/addon_configs/a0d7b954_appdaemon/apps/smart_vent_controller.py
HOST=root@homeassistant.local
PORT=2222

echo "=== 0. expected local commit ==="
git -C /Users/adam.durham/repos/homelab log --oneline -1
echo

echo "=== 1. LOCAL sha256 ==="
LOCAL_SHA=$(shasum -a 256 "$APP" | awk '{print $1}')
echo "$LOCAL_SHA  (local)"
echo

echo "=== 2. LIVE sha256 BEFORE deploy (drift check) ==="
ssh -p $PORT $HOST "sha256sum $REMOTE" || { echo "SSH FAILED — unlock 1Password and retry"; exit 1; }
echo

echo "=== 3. scp ==="
scp -P $PORT "$APP" "$HOST:$REMOTE" || { echo "SCP FAILED"; exit 1; }
echo

echo "=== 4. LIVE sha256 AFTER deploy — must match local ==="
REMOTE_SHA=$(ssh -p $PORT $HOST "sha256sum $REMOTE" | awk '{print $1}')
echo "$REMOTE_SHA  (remote)"
if [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then
  echo "*** SHA256 MATCH — byte-identical deploy confirmed ***"
else
  echo "*** SHA256 MISMATCH — DO NOT TRUST THIS DEPLOY ***"; exit 1
fi
echo

echo "=== 5. waiting 45s for AppDaemon hot-reload ==="
sleep 45

echo "=== 6. reload log — must show a clean restart with NO traceback ==="
ssh -p $PORT $HOST "ha addons logs a0d7b954_appdaemon" 2>&1 | tail -60
echo
echo "=== 7. grep the log for trouble ==="
ssh -p $PORT $HOST "ha addons logs a0d7b954_appdaemon" 2>&1 | tail -200 \
  | grep -iE "traceback|error|exception|AttributeError|PRE-COOL|precool" | tail -30
echo
echo "If step 6/7 show a clean reload, confirm the new sensor with:"
echo "  cd /Users/adam.durham/repos/homelab && source homeassistant/ha_config.env && \\"
echo "  curl -s -H \"Authorization: Bearer \$HA_TOKEN\" \"\$HA_URL/api/states/sensor.smart_vent_precool\" | python3 -m json.tool"
