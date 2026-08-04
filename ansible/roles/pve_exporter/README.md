# roles/pve_exporter

Installs `prometheus-pve-exporter` on vm-01 (co-located with
VictoriaMetrics), a Python venv service scraping the Proxmox API and
exposing Prometheus-format metrics on `:9221`. Complements
`roles/pve_metrics_export` (pvestatd's native InfluxDB push): that role
gets node + per-guest CPU/mem/disk/net, this one gets the layers pvestatd
doesn't push -- storage pool usage, replication job status/duration, HA
resource state, and guests not covered by any backup job.

## Why this instead of / alongside pve_metrics_export

Both exist deliberately, covering different layers:

- **`pve_metrics_export` (push, native, built 2026-08-04 earlier today):**
  zero new software -- pvestatd pushes InfluxDB line-protocol straight to
  VM. Fast to add, but pvestatd's native export only carries basic
  resource-usage metrics.
- **`pve_exporter` (this role, pull, Python service):** more moving parts
  (new venv service + a scoped API token), but exposes real
  replication-job status/duration (`pve_replication_duration_seconds`,
  `pve_replication_last_sync_timestamp_seconds`,
  `pve_replication_failed_syncs`), HA resource state (`pve_ha_state`),
  backup-job coverage (`pve_not_backed_up_info` /
  `pve_not_backed_up_total`), and storage-pool usage
  (`pve_disk_usage_bytes{id=~"storage/.*"}` /
  `pve_disk_size_bytes`) -- none of which pvestatd's push carries.
  Directly useful for alerting on the 2026-08-04 replication-burst
  root-cause fix (`docs/ipam.md`) and the frigate HA node-affinity rule
  (`roles/frigate_host`).

## Auth

Uses a dedicated read-only Proxmox user + API token, NOT the existing
`root@pam!hermes-automation` token (full `Sys.Modify` privileges --
inappropriate to embed in a long-running exporter config file on a
service host):

```
pveum user add pve-exporter@pve --comment "Read-only account for prometheus-pve-exporter"
pveum aclmod / -user pve-exporter@pve -role PVEAuditor
pveum user token add pve-exporter@pve exporter --privsep 0 --comment "prometheus-pve-exporter token"
```

`--privsep 0` means the token inherits the user's own permissions
(PVEAuditor, read-only, cluster-wide) rather than needing separate ACLs
on the token itself. Credentials vaulted as
`vault_pve_exporter_token_id` / `vault_pve_exporter_token_secret` in
`group_vars/all/vault.yml`.

## TLS

`verify_ssl: true` in the rendered config -- NOT the usual homelab
`verify_ssl: false` cop-out. Each pve node is scraped by its ACME-issued
FQDN (`pve01.chi.lab.amd-e.com`, matching `roles/proxmox_acme`'s real
Let's Encrypt cert CN) rather than a bare IP, so certificate validation
actually passes. Verified live: `curl -v
https://pve01.chi.lab.amd-e.com:8006/...` from vm-01 returns "SSL
certificate verify ok."

## What it does

Same venv-install pattern as `roles/adguard_log_shipper`: dedicated
system user, `python3 -m venv`, `pip install prometheus-pve-exporter`,
config + systemd unit, enable + start.

Collector flags: none set explicitly. Verified against the installed
version's `cli.py` source -- every collector we want (`replication`,
`backup-info`, `resources`, `status`, etc.) is enabled BY DEFAULT; only
`--no-collector.X` flags exist to disable one. The `config` collector
(one extra API call per guest) is left at its default (on) since this
cluster's guest count is small enough it isn't the "big deployment"
case the upstream README warns about.

## Where it's invoked

`deploy_monitoring.yml` -- "Install pve_exporter" play, targeting the
`victoriametrics` group (i.e. vm-01), alongside the existing
VictoriaMetrics/blackbox/Loki/Alloy installs.

## Scrape config

Lives in `roles/victoriametrics/templates/prometheus.yml.j2` (job
`pve_exporter`), NOT duplicated here -- one static target per
`proxmox_nodes` inventory host, `cluster=1&node=1` params, relabeled to
hit the exporter's single `127.0.0.1:9221/pve` endpoint per the
exporter's own documented pattern (`target` URL param picks which node
to scrape).

## Verifying data is arriving

```
curl -s 'http://<vm-01>:8428/api/v1/label/__name__/values' | grep ^pve_
```

Expect `pve_replication_duration_seconds`,
`pve_disk_usage_bytes{id=~"storage/.*"}`, `pve_ha_state`, `pve_up`,
`pve_guest_info`, etc. Verified live 2026-08-04: `up{job="pve_exporter"}`
== 1 for all 3 nodes, 20 series of `pve_replication_duration_seconds`,
1431 series of `pve_ha_state`, 27 series of storage-object
`pve_disk_usage_bytes`.
