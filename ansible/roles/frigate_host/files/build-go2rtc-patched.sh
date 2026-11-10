#!/usr/bin/env bash
# Build the patched go2rtc binary the Frigate container mounts at
# /config/go2rtc (=> /opt/frigate/go2rtc/go2rtc_patched on the CT).
#
# Run ON frigate-01 (CT 170) as the `amd` user. Building needs no root; only
# the install step at the end does (sudo, YubiKey-gated on fleet hosts).
#
#   ./build-go2rtc-patched.sh 1.9.15          # build only -> ~/go2rtc_1.9.15_patched
#   ./build-go2rtc-patched.sh 1.9.15 --install # build + swap in + restart Frigate
#
# WHY THE PATCH (files/go2rtc-nest.patch):
#   * per-camera API instances so 6 Nest cameras don't share one extend timer
#   * the Nest stream-extend timer re-arms forever (stock fires once, stream
#     dies ~5 min in)
#   * a global dial mutex serializes SDM negotiation to avoid HTTP 429
#   * ExchangeSDP retry/backoff removed (conflicts with the serialized dial)
#
# WHY A LOCAL BUILD: Home Assistant's go2rtc integration raises a
# `recommended_version` repair when the connected server is older than the
# version it recommends. HA points at this server (configuration.yaml
# `go2rtc: url: http://192.168.86.17:1984`), so the binary must track upstream.
#
# Static build only (CGO_ENABLED=0): a dynamically linked build from a newer
# glibc dies in Frigate's Debian Bookworm image ("Verneed record").

set -euo pipefail

VERSION="${1:-1.9.15}"
INSTALL="${2:-}"
GO_VERSION="1.26.0"          # go.mod of go2rtc v1.9.15 requires >= 1.26
GO_HOME="$HOME/go-toolchain"
SRC="$HOME/go2rtc-$VERSION"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$HOME/go2rtc_${VERSION}_patched"

if [ ! -x "$GO_HOME/go/bin/go" ]; then
  echo "installing Go $GO_VERSION toolchain into $GO_HOME"
  curl -sSL -o /tmp/go.tgz "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz"
  mkdir -p "$GO_HOME"
  tar -C "$GO_HOME" -xzf /tmp/go.tgz
  rm -f /tmp/go.tgz
fi

if [ ! -d "$SRC/.git" ]; then
  git clone --filter=blob:none https://github.com/AlexxIT/go2rtc "$SRC"
fi
cd "$SRC"
git fetch --tags --quiet
git checkout --quiet "v$VERSION"
git reset --hard --quiet "v$VERSION"

git apply --3way "$PATCH_DIR/go2rtc-nest.patch"
git -c user.name=amd -c user.email=amd@frigate-01 \
  commit --quiet -am "nest: per-camera API instances, re-arming extend timer, dial mutex (carried patch)"

# Second patch: a local sliding-window quota limiter. Google caps
# ExecuteDeviceCommand at 10/min per project+user (5/min per device+command,
# 30/min and 100/h per camera); six cameras dialing at boot plus retries blew
# through it and every camera starved on 429. The limiter books a slot in each
# window before a call goes out and holds the project off for a minute after a
# real 429. Verified: no 429s in steady state, calls log
# "nest: call dev=… cmd=… status=200".
git apply --3way "$PATCH_DIR/go2rtc-nest-quota.patch"
git -c user.name=amd -c user.email=amd@frigate-01 \
  commit --quiet -am "nest: sliding-window Device Access quota limiter (carried patch)"

PATH="$GO_HOME/go/bin:$PATH" CGO_ENABLED=0 \
  go build -trimpath -ldflags "-s -w" -o "$OUT" .

echo "built: $OUT"
file "$OUT"

# Smoke test on a scratch port before anyone installs it.
printf 'api:\n  listen: "127.0.0.1:11985"\nrtsp:\n  listen: ""\nlog:\n  level: error\n' > /tmp/g2r-test.yml
"$OUT" -config /tmp/g2r-test.yml >/tmp/g2r-test.log 2>&1 &
PID=$!
sleep 3
curl -s -m 4 http://127.0.0.1:11985/api || true
echo
kill "$PID" 2>/dev/null || true
sleep 1
kill -9 "$PID" 2>/dev/null || true
rm -f /tmp/g2r-test.yml /tmp/g2r-test.log

if [ "$INSTALL" = "--install" ]; then
  TS=$(date +%Y%m%d)
  sudo cp -a /opt/frigate/go2rtc/go2rtc_patched \
             "/opt/frigate/go2rtc/go2rtc_patched.pre-$VERSION.bak.$TS"
  sudo install -m 755 -o root -g root "$OUT" /opt/frigate/go2rtc/go2rtc_patched
  sudo docker restart frigate
  echo "installed; waiting for Frigate..."
  sleep 25
  curl -s -m 5 http://127.0.0.1:1984/api || true
  echo
  echo "then verify: curl -s localhost:5000/api/stats | jq '.cameras|map_values(.camera_fps)'"
  echo "and clear HA's stale repair: repairs/ignore_issue go2rtc recommended_version"
fi
