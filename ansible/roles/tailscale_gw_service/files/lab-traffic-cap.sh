#!/bin/bash
# Shared 100Mbps internet cap for noisy lab CTs (2026-08-25).
# Scoped to media-ingest-02 (172.16.0.48) + tg-harvester-01 (172.16.0.46).
# Other SDN CTs (lb-01, authentik, dns-01, graf-01, hermes-gw) are NOT capped.
# eth0 egress = lab upload to internet; eth1 egress = lab download.
set -e
for dev in eth0 eth1; do tc qdisc del dev $dev root 2>/dev/null || true; done
tc qdisc add dev eth0 root handle 1: htb default 999
tc class add dev eth0 parent 1: classid 1:999 htb rate 950mbit
tc class add dev eth0 parent 1: classid 1:100 htb rate 100mbit ceil 100mbit
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip src 172.16.0.48/32 flowid 1:100
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip src 172.16.0.46/32 flowid 1:100
tc qdisc add dev eth1 root handle 1: htb default 999
tc class add dev eth1 parent 1: classid 1:999 htb rate 950mbit
tc class add dev eth1 parent 1: classid 1:100 htb rate 100mbit ceil 100mbit
tc filter add dev eth1 parent 1: protocol ip prio 1 u32 match ip dst 172.16.0.48/32 flowid 1:100
tc filter add dev eth1 parent 1: protocol ip prio 1 u32 match ip dst 172.16.0.46/32 flowid 1:100
