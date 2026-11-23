# Hourly Wi-Fi / LAN health check

Home Assistant is both the scheduler **and** the wired tester; amd-workstation is only allowed to measure Wi-Fi
(owner's rule, 2026-11-23: "everything physically cabled can likely be done from the HA box itself").

```
Home Assistant box (192.168.86.2)
  ├─ sensor.network_health_wired   (command_line, every 3600 s)         homeassistant/command_line.yaml
  │    └─ python3 /config/scripts/net_wired.py                          homeassistant/scripts/net_wired.py
  │         • ICMP loss/latency  -> 4 mesh nodes, AT&T gw, both resolvers, WAN
  │         • DNS query time     -> .4 / .5 (raw UDP, uncached name)
  │         • Nest router API    -> uptime / mesh channel / WAN state
  │         • one real DHCP DISCOVER -> offer count
  │         • 45 s wired multicast/broadcast census -> top sources, ARP share
  └─ sensor.network_health        (command_line, every 3600 s)
       └─ ssh -i /config/.ssh/id_net_health adam.durham@192.168.86.19 run
            └─ forced command: python3 ~/.hermes/scripts/net_health.py --json
                 ├─ reads sensor.network_health_wired (everything cabled, measured on HA)
                 ├─ 45 s ch149/80 MHz monitor capture on the idle AX210   [root, docker chroot: net_health_root.sh]
                 ├─ nmcli scan: per-BSSID channel of every 4D4C radio     (Wi-Fi only)
                 ├─ reads HA's hourly Ookla numbers
                 ├─ writes /var/lib/prometheus/node-exporter/netheal.prom -> node_exporter -> VictoriaMetrics
                 │    -> Grafana "Network & Wi-Fi Health" (uid network-health)
                 └─ prints one JSON line (flag count + key numbers) back to HA
```

Why the workstation for the capture only: the monitor-mode 5 GHz capture needs its idle Intel AX210 and the privileged
docker chroot; the HA Green has no Wi-Fi radio. Everything cabled is measured on HA.

## Files (live copies: `~/.hermes/scripts/` on amd-workstation, `/config/scripts/` on the HA host; this directory is the
version-controlled mirror — change both)
- `net_health.py` – the Wi-Fi collector (`--verbose` manual run, `--json`/`run` machine mode, `--parse-only air.pcap`)
- `net_health_root.sh` – the root half (ch149 monitor capture only), run inside `docker run --privileged ... chroot /host`
- `net_health_digest.py` – prints a 24 h summary from `~/.hermes/cache/net-health/hourly.jsonl`
- `gen_dash.py` – generates `ansible/roles/grafana/files/network_health.json`
- `homeassistant/scripts/net_wired.py` in this repo (live: `/config/scripts/net_wired.py`) – the HA-side wired probe

## Access
HA's key is a dedicated ed25519 key, 0600, only on the HA host (`/config/.ssh/id_net_health`, not in git). On the
workstation its `authorized_keys` line is restricted: `from="192.168.86.2",no-pty,no-port-forwarding,no-X11-forwarding,
no-agent-forwarding,command="/usr/bin/python3 /home/adam.durham/.hermes/scripts/net_health.py --json"` — it can run that one
script and nothing else. Rotate by generating a new key, replacing both ends, deleting the old line.

## Flags it raises (collector prints them, HA sensor carries them as attributes)
wired node ping loss/slow, WAN loss/slow/low speed, DNS slow, router rebooted, DHCP offers != 1, radio channel change,
broadcast flood (>15/s from one source), 5 GHz ch149 busy (>55 % airtime), mesh multicast airtime >8 %, airtime offender
(>8 % air, or >3 % with >50 % retries), missing beacons, HA wired sensor stale/unreadable, HA's Ookla stale/low, new LAN device.

## Things learned
- Wired probes moved to the HA Green on 2026-11-23. Its view of the router is ~10 ms (an ARM SBC's reply path) where the
  workstation saw 0.3 ms, so `SLOW_MS` allows `router .1` 25 ms and `AT&T gw` 60 ms; the mesh nodes keep 8 ms.
- A new `command_line` sensor needs an HA **restart** — `homeassistant.reload_core_config` returns 200 and adds nothing.
- The ecobee ARP flood fix (manual 192.168.86.6/29 on the thermostat) is recorded in `docs/ecobee-lan-scan.md`.
- A WAN speed test already exists (HA's hourly Ookla, `sensor.ookla_speedtest*`); this check only reads it.
