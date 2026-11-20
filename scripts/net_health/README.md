# Hourly Wi-Fi / LAN health check

Home Assistant is the scheduler; amd-workstation does the measuring; Grafana shows the result.

```
HA sensor.network_health (command_line, every 3600 s)            homeassistant/command_line.yaml
   └─ ssh -i /config/.ssh/id_net_health adam.durham@192.168.86.19 run
        └─ forced command (authorized_keys): python3 ~/.hermes/scripts/net_health.py --json
             ├─ pings / DNS / router status / HA's Ookla numbers
             ├─ 45 s Ethernet multicast census + 45 s ch149/80 MHz monitor capture (AX210)   [root, via docker chroot: net_health_root.sh]
             ├─ one DHCP DISCOVER, iperf3 Mac <-> workstation over Wi-Fi, MacBook ~/wifi-health.csv summary
             ├─ writes /var/lib/prometheus/node-exporter/netheal.prom   -> node_exporter -> VictoriaMetrics -> Grafana "Network & Wi-Fi Health"
             └─ prints one JSON line (flag count + key numbers) back to HA
```

Why the workstation: the monitor-mode capture needs its idle Intel AX210, the multicast census needs its wired NIC,
the iperf3 server and the privileged docker chroot live there. The HA Green has no Wi-Fi radio.

## Files (live copies are in `~/.hermes/scripts/` on amd-workstation; this directory is the version-controlled mirror — change both)
- `net_health.py` – the collector (`--verbose` manual run, `--json`/`run` machine mode, `--parse-only air.pcap mc.pcap`)
- `net_health_root.sh` – the root half (captures + DHCP probe), run inside `docker run --privileged ... chroot /host`
- `net_health_digest.py` – prints a 24 h summary from `~/.hermes/cache/net-health/hourly.jsonl`
- `gen_dash.py` – generates `ansible/roles/grafana/files/network_health.json`

## Access
HA's key is a dedicated ed25519 key, 0600, only on the HA host (`/config/.ssh/id_net_health`, not in git). On the
workstation its `authorized_keys` line is restricted: `from="192.168.86.2",no-pty,no-port-forwarding,no-X11-forwarding,
no-agent-forwarding,command="/usr/bin/python3 /home/adam.durham/.hermes/scripts/net_health.py --json"` — it can run that one
script and nothing else. Rotate by generating a new key, replacing both ends, deleting the old line.

## Flags it raises (collector prints them, HA sensor carries them as attributes)
wired node ping loss/slow, WAN loss/slow/low speed, DNS slow, router reboot, DHCP offers != 1, radio channel change,
broadcast flood (>15/s from one source), 5 GHz ch149 busy (>55 % airtime), mesh multicast airtime >8 %, airtime offender
(>8 % air, or >3 % with >50 % retries), missing beacons, Wi-Fi throughput <50 Mbps, HA's Ookla stale/low, new LAN device.

## Things learned
- 6 GHz at -43 dBm: 500-700 Mbps each way; the same Mac on 5 GHz scp gave 20-30 Mbps.
- The ecobee ARP flood fix (manual 192.168.86.6/29 on the thermostat) is recorded in `docs/ecobee-lan-scan.md`.
- A WAN speed test already exists (HA's hourly Ookla, `sensor.ookla_speedtest*`); this check only reads it.
