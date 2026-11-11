#!/bin/sh
# Keep NAT-PMP port mappings alive for go2rtc's WebRTC media.
#
# Two different sockets matter:
#   8555         go2rtc's own WebRTC server (browser / RTSP clients)
#   8561-8566    the Pion PeerConnections of the nest: sources, one per camera
#                (pinned via go2rtc `webrtc.filters.udp_ports`)
#
# The nest media sockets used to be ephemeral, which is why the router dropped
# their mapping after ~60 s and every camera died 1-2 minutes in. Nest Wifi has
# no admin API and no UPnP IGD, but it answers NAT-PMP, so this timer renews the
# mappings itself - nobody needs to touch the Google Home app.
set -u
GATEWAY=${GATEWAY:-192.168.86.1}
LIFETIME=7200

renew() {
    port=$1
    proto=$2
    out=$(natpmpc -g "$GATEWAY" -a "$port" "$port" "$proto" "$LIFETIME" 2>&1) || {
        echo "natpmp $proto/$port failed: $out" >&2
        return 1
    }
    echo "$out" | grep -q "Mapped public port" || {
        echo "unexpected natpmp reply for $proto/$port: $out" >&2
        return 1
    }
    echo "renewed $proto/$port"
}

rc=0
renew 8555 udp || rc=1
for port in 8561 8562 8563 8564 8565 8566; do
    renew "$port" udp || rc=1
done
exit "$rc"
