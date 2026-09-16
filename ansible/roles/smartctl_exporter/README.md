# roles/smartctl_exporter

Periodic SMART attribute dump to a Prometheus textfile, picked up by
Alloy's `prometheus.exporter.unix` textfile collector (see
`roles/alloy`) and shipped to VictoriaMetrics like every other host
metric in the fleet.

## Why this exists

Added 2026-09-16 after investigating pve02/pve03's aging SATA boot
HDDs (ST500LM034-2GH17A / ST500LM021-1KJ152 — see homelab docs on the
Sep 10 EXT4 corruption incident). `smartd` was already running on both
nodes with real self-test schedules and alert thresholds, but its
alert delivery path is `/usr/bin/mail` via `proxmox-mail-forward` —
local root mailbox, unverified to reach anyone, and completely
disconnected from the fleet's actual alert pipeline (Grafana ->
grafana-ack-bot -> Discord, see `roles/grafana_ack_bot`). A drive could
silently accumulate pending/reallocated sectors for weeks with the
only record sitting unread in `/var/mail/root`.

This role doesn't replace smartd (still useful for its own local self-
test scheduling) — it adds a second, independent path: dump the
attributes that actually predict failure (reallocated sector count,
current pending sector, offline uncorrectable, command timeout, UDMA
CRC errors, overall health) as Prometheus metrics every 5 minutes, so
Grafana can alert on a *trend* (e.g. reallocated sectors climbing
week-over-week) rather than a one-shot local mail nobody reads.

## What it does

- Installs `/usr/local/bin/smartctl-textfile.sh`, which runs
  `smartctl -a -j` against each device in `smartctl_exporter_devices`,
  parses the JSON with Python (already present — Proxmox ships
  python3), and writes Prometheus-format metrics to
  `{{ smartctl_exporter_textfile_dir }}/smartctl.prom`. Written
  atomically (tmp file + `mv`) since the textfile collector scans this
  directory on every Alloy scrape and a half-written file would be
  parsed as corrupt.
- A `smartctl-textfile.timer` runs the script every
  `smartctl_exporter_interval` (default 5min).
- Metrics exposed: `smartctl_device_scrape_success`,
  `smartctl_device_health_passed`, and `smartctl_device_attribute`
  (labeled `disk`, `attribute`, `id`) for reallocated_sector_ct (5),
  power_on_hours (9), end_to_end_error (184), reported_uncorrect (187),
  command_timeout (188), airflow_temperature_cel (190),
  temperature_celsius (194), reallocated_event_count (196),
  current_pending_sector (197), offline_uncorrectable (198),
  udma_crc_error_count (199).
  IMPORTANT: `smartctl -j`'s `raw.value` field is packed with extra
  vendor data for some attributes (seen live: Power_On_Hours
  raw.value=261692357380596 while raw.string="35316 (238 2 0)" — same
  packing on 190/194/196). The script parses the leading integer out
  of `raw.string` instead, which is correct for both packed and plain
  attributes (verified raw.value == int(raw.string) exactly for 5,
  184, 187, 188, 197, 198, 199).
- Renders `/etc/udev/rules.d/60-sata-error-recovery-timeout.rules`,
  raising the kernel SCSI command timeout for each device in
  `smartctl_exporter_devices` from the 30s default to
  `smartctl_exporter_scsi_timeout` (default 180s), applied immediately
  via `udevadm trigger` (not just on next reboot). Root cause
  (2026-09-16): pve02/pve03's boot HDDs don't support SCT Error
  Recovery Control, so a slow internal error-recovery attempt exceeds
  the kernel's 30s timeout and the SATA link gets reset mid-recovery,
  failing every in-flight command — this is what corrupted
  pve-cluster's config.db on pve03 on 2026-09-10. This is the real fix
  for that failure class (give the drive the time it needs), not a
  retry/backoff mitigation.
- Renders `/etc/systemd/journald.conf.d/99-volatile-hdd-wear.conf`,
  switching journald to RAM-backed (`Storage=volatile`) storage.
  Alloy already ships this host's journal to Loki in real time, so
  there's no observability loss — this removes a continuous small-
  write+fsync load from the disk being kept alive as long as possible.

## Key variables (`defaults/main.yml`)

- `smartctl_exporter_devices` — block devices to poll (default
  `[/dev/sda]`, the actual pain point on pve02/pve03). Override per-host
  in inventory for hosts with a different disk layout worth tracking.
- `smartctl_exporter_textfile_dir` — must match the `directory` set in
  the `prometheus.exporter.unix` `textfile` block in
  `roles/alloy/templates/config.alloy.j2`.
- `smartctl_exporter_interval` — systemd timer `OnUnitActiveSec` value.

## Wiring into Alloy

`roles/alloy/templates/config.alloy.j2` needs `enable_collectors` to
include `"textfile"` and a `textfile { directory = "..." }` block
pointing at `smartctl_exporter_textfile_dir`, gated on a
`smartctl_exporter_enabled` host var so hosts without this role
installed don't get an exporter block pointed at an empty directory.

## Where it's invoked

Add to `deploy_monitoring.yml`'s proxmox_nodes play (or a new
`hosts: proxmox_nodes` play) alongside `pve_metrics_export` — this is
specifically for the pve node hosts' own boot-disk health, not guest
VMs/CTs.

## Alert rules

See `roles/grafana/templates/alerting_rules.yml.j2` —
`sata_boot_disk_reallocated_sectors_climbing` and
`sata_boot_disk_pending_sector_nonzero` query
`smartctl_device_attribute` for exactly this reason.
