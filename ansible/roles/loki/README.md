# roles/loki

Loki (Grafana's log aggregation) on vm-01. Receives journal logs pushed
by Alloy from every managed host.

## What it does

- Downloads `loki-linux-amd64.zip` from the version pinned by
  `loki_version`.
- Renders `/etc/loki/loki.yml` (config) + systemd unit.
- Storage: filesystem-backed chunks + index in
  `{{ loki_storage_dir }}` (default `/var/lib/loki`).
- Retention: 14 days (`loki_retention_period: 336h`).

## Key variables (`defaults/main.yml`)

- `loki_version` — Renovate-tracked. Verify schema_config / compactor
  notes before bumping; Loki 3.x has shifted both across point releases.
- `loki_port` — 3100 (push API + query).
- `loki_storage_dir`, `loki_retention_period`.

## Disk pressure

The `/var/lib/loki` directory lives on `/` on vm-01. A `loki_disk_pressure`
Grafana alert fires at 70% of `/` full to give headroom for chunk
pruning before the generic `disk_full` alert (90%) catches it.

## Where it's invoked

`deploy_monitoring.yml`'s play 3 (`Configure VictoriaMetrics`, alongside
the `loki` role-include).

## History

`docs/loki-upgrade-plan.md` covers the 3.0.0 → 3.7.1 upgrade that
landed alongside the Promtail → Alloy migration.
