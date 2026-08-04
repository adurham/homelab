# roles/pve_metrics_export

Registers VictoriaMetrics (vm-01) as Proxmox's built-in external metric
server, using the InfluxDB v2 HTTP write path. pvestatd already collects
node + per-guest (VM/CT) resource metrics -- CPU, memory, disk, network --
every 10s for the GUI's RRD graphs; this just exports the same data
somewhere with real retention/query, no new agent needed.

## Why this instead of prometheus-pve-exporter

Two ways exist to get Proxmox metrics into VictoriaMetrics:

- **This role (push, native):** pvestatd pushes InfluxDB line-protocol
  directly to VM's `/api/v2/write` -- VM already speaks this natively
  (see VictoriaMetrics' InfluxDB integration docs), same host:port Alloy
  already remote_writes to. Zero new software, zero new firewall rules
  (vm-01/pve nodes already reach each other over the private SDN --
  `roles/pve_private_ip`). Gets node + guest CPU/mem/disk/net.
- **prometheus-pve-exporter (pull, considered but not built yet):** would
  need a new role/service + a limited Proxmox API token + a scrape target
  in `roles/victoriametrics`. Richer data -- storage pool usage, HA
  resource state, replication job status/duration, backup job status --
  none of which pvestatd's native export includes. Worth adding later
  specifically to alert on the 2026-08-04 replication-burst root-cause
  fix and the frigate HA node-affinity rule; deliberately deferred, not
  because it's a bad idea.

## What it does

Idempotent `pvesh create /cluster/metrics/server/{{ pve_metrics_id }}`
against `/etc/pve/status.cfg` (pmxcfs -- cluster-wide config, write once
from any node, replicates automatically). Checked via
`pvesh get /cluster/metrics/server` first so re-runs don't error on
"already exists", same pattern as the frigate HA-rule task in
`roles/frigate_host`.

## Key variables (`defaults/main.yml`)

- `pve_metrics_id` -- the metric-server config's id (`vm-01-influx`).
- `pve_metrics_server` / `pve_metrics_port` -- defaults to `{{ ip_vm }}`
  (vm-01's private-SDN IP) : 8428, VM's query/write port.
- `pve_metrics_bucket` -- InfluxDB "bucket" tag VM stores under the `db`
  label (`proxmox`). No token needed -- VM's write endpoint doesn't
  require auth on this network.

## Verifying data is arriving

```
curl -s 'http://<vm-01>:8428/api/v1/label/__name__/values' | grep proxmox
```

Series land prefixed `proxmox_<field>` (per VictoriaMetrics' InfluxDB
line-protocol field-name mapping), tagged by `object` (`node`/`qemu`/`lxc`),
`id`, and `nodename`.

## Where it's invoked

`pve_host_hardening.yml` -- runs alongside the other one-time PVE
cluster-config plays (firewall, SSH hardening).
