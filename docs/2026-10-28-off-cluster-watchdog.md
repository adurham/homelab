# Alerting that survives the cluster — HA-box watchdog (2026-10-28)

## The gap this closes

Every alert in the lab was raised **by the cluster, about the cluster**:

- Grafana (`graf-01`, CT 107) evaluates the rules and lives on **pve03**.
- The Discord ack/silence bot (`hermes-gw-01`, CT 113) also lives on **pve03**.
- VictoriaMetrics and Loki scrape targets are cluster guests too.

So a pve03 failure, a cluster-wide power loss, or a dead switch produced the one
outcome an alerting system must never produce: silence that looks like calm.
This was called out during the 2026-10-27 review and is what this change fixes.

## What was added, and where

The Home Assistant box (`192.168.86.2`) is separate hardware on the same LAN and
is not a Proxmox guest, so it keeps running when the cluster does not. It now
watches the cluster:

**`/config/command_line.yaml`** (appended, three entities):

| entity | probe |
|---|---|
| `binary_sensor.pve01_reachable` | TCP connect to `192.168.86.11:8006` |
| `binary_sensor.pve02_reachable` | TCP connect to `192.168.86.12:8006` |
| `binary_sensor.pve03_reachable` | TCP connect to `192.168.86.13:8006` |

TCP on the Proxmox web UI, **not ICMP**: the nodes drop ping entirely — measured
100 % packet loss from the HA box to all three addresses while
`https://192.168.86.11:8006` answered `200` in the same session. A ping-based
watchdog here would have been permanently red. Each probe runs every 60 s with a
4 s timeout, matching the existing `amd-workstation reachable` sensor's pattern.

**`/config/automations/cluster_watchdog.yaml`** (new):

`Infrastructure: Proxmox cluster watchdog` (`id:
infrastructure_proxmox_cluster_watchdog`) fires when **all three** nodes have been
`off` for **10 minutes** — one `for:` trigger per node plus a condition on the
other two, so a single node reboot never pages. Action: `notify.mobile_app_…`
straight to the phone, plus a persistent notification.

It deliberately does **not** route through Grafana or Discord, because those are
the things that are missing when it fires.

## Verified

- `ha core check` passes; entities picked up with `automation.reload` +
  `command_line.reload` — no core restart, no HA downtime.
- All three sensors report `on` against the live nodes.
- `automation.infrastructure_proxmox_cluster_watchdog` exists and is enabled.
- The notification leg was exercised directly (one test push to the phone,
  HTTP 200) rather than by faking a cluster outage.

Backups of the two files before the edit: `/config/command_line.yaml.bak-<stamp>`
and `/config/automations.bak-<stamp>/`.

## What it does not cover

- **Internet loss** — the phone push rides Home Assistant Cloud; with no WAN
  there is no out-of-band channel that does not involve new hardware.
- **The HA box itself dying** — that is the remaining single point of failure for
  alerting, and the honest answer is that it would be discovered by absence of
  everything, not by a page.
- **Per-service failures** (a dead container on a live cluster) — still Grafana's
  job, and unchanged.
