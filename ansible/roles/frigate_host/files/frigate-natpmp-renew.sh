#!/bin/sh
# Keep a NAT-PMP port mapping for go2rtc's WebRTC media alive.
#
# Nest Wifi has no admin API and no UPnP IGD, but it does answer NAT-PMP, so the
# frigate CT can open its own UDP 8555 mapping without anyone touching the
# Google Home app. The mapping has a lifetime (7200 s), hence this timer.
set -u
GATEWAY=192.168.86.1
PORT=8555
LIFETIME=7200

out=$(natpmpc -g "$GATEWAY" -a "$PORT" "$PORT" udp "$LIFETIME" 2>&1) || {
    echo "natpmp failed: $out" >&2
    exit 1
}
echo "$out" | grep -q "Mapped public port" || {
    echo "unexpected natpmp reply: $out" >&2
    exit 1
}
echo "renewed UDP $PORT -> $GATEWAY (lifetime ${LIFETIME}s)"
