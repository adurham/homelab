# roles/qga_disk_export

Agentless per-guest disk-usage export for the running TanOS QEMU VMs,
via the QEMU Guest Agent (QGA) and a Prometheus textfile, picked up by
Alloy's `prometheus.exporter.unix` textfile collector (see `roles/alloy`)
and shipped to VictoriaMetrics like every other host metric in the fleet.

## Why this exists

The six Tanium appliance VMs (`ts-01/ts-02`, `tms-01/tms-02`,
`tzs-01/tzs-02`) are vendor TanOS appliances and per explicit direction
must not run custom software (see the retired-agent note at the bottom of
`deploy_monitoring.yml` — `tanium_cluster` runs **no** monitoring agent).
That rules out an in-guest node_exporter, so those guests previously had
**no** `node_filesystem_*` series at all and the Grafana `disk_full` rule
could never see them.

They do, however, all run the QEMU Guest Agent, which is part of the
appliance image. `qm guest cmd <vmid> get-fsinfo` returns each mount's
`total-bytes` / `used-bytes` over that pre-existing channel — **zero
in-guest installs**, nothing to maintain on the appliance.

## How it works

- Installs `/usr/local/bin/qga-disk-textfile.sh`, which:
  1. Enumerates running local VMs (`qm list | awk 'NR>1 && $3=="running"'`),
  2. runs `timeout 15 qm guest cmd <vmid> get-fsinfo` for each,
  3. parses the JSON array with Python (already present — Proxmox ships
     `python3`), and
  4. writes Prometheus-format metrics to
     `{{ qga_disk_export_textfile_dir }}/qga_disk.prom`, atomically
     (tmp file + `mv`) since the textfile collector scans this directory
     on every Alloy scrape and a half-written file would be parsed as
     corrupt. Output is sorted for stable, diff-friendly diffs.
- A `qga-disk-textfile.timer` runs the script every
  `qga_disk_export_interval` (default 5min).

### IMPORTANT: `qm guest cmd` only works on the hosting node

`qm guest cmd` talks to a VM over the local qmp/virtio-serial channel, so
it works **only on the pve node actually hosting the VM**. This role is
therefore installed on every pve node (one timer per node) and each node
only ever sees its own running guests. Node → guest map at the time of
writing: pve02 hosts `ts-01`(200)/`tms-01`(202)/`tzs-01`(204), pve03 hosts
`ts-02`(201)/`tms-02`(203)/`tzs-02`(205), pve01 has no running QEMU VMs.
There is no cross-node aggregation — each node's own textfile carries only
its guests, and VictoriaMetrics sees the union via per-node scrapes.

### Metrics exposed

For every mountpoint of every running guest:

```
node_filesystem_size_bytes{guest="<vmname>",mountpoint="<mp>",fstype="<type>",device="<name>"} <total-bytes>
node_filesystem_free_bytes{...} <max(0, total-bytes - used-bytes)>
node_filesystem_avail_bytes{...} <same as free>
```

plus one per guest:

```
qga_disk_scrape_success{guest="<vmname>"} 1   # or 0 if get-fsinfo failed / timed out
```

The metric names deliberately reuse `node_filesystem_*` so the existing
`disk_full` rule covers these series **unchanged** — it already selects on
`fstype!~"tmpfs|overlay|squashfs|devtmpfs"`, which these ext4/vfat mounts
satisfy.

### The `guest` label contract

Every row carries `guest="<vmname>"` (the VM name from `qm list`, e.g.
`ts-01`). This is the contract the Grafana rule relies on: `disk_full`'s
branch C sets `display` from the series `instance` (the pve node's
node_exporter instance) and then **conditionally overwrites it with
`guest` when present**, so an alert on an appliance VM names the guest
(`ts-01`) instead of the hosting node (`pve02`). See the double
`label_replace` in `roles/grafana/templates/alerting_rules.yml.j2`
(branch C of `disk_full`) and the "Alert rules" section below.

### `avail` is an approximation (documented deviation from node_exporter)

node_exporter computes `node_filesystem_avail_bytes` from `statfs`
`f_bavail` — the space available to an **unprivileged** process, which is
`f_bfree` minus the root-reserved blocks. QGA's `get-fsinfo` exposes only
`total-bytes` and `used-bytes`, with no `f_bavail`/reserved figure, so
this role sets `free == avail == total - used`. That slightly *overstates*
availability on a filesystem with reserved blocks (typically 5% on ext4),
making the computed `100 - avail/size*100` slightly **understate** usage.
The `disk_full` rule fires above 90%, far above that error band, so the
approximation is acceptable — and it is the best figure QGA can supply.
Do not "fix" this by inventing a reserved-blocks estimate.

## Key variables (`defaults/main.yml`)

- `qga_disk_export_textfile_dir` — must match the `directory` set in the
  `prometheus.exporter.unix` `textfile` block in
  `roles/alloy/templates/config.alloy.j2`. Same directory as the smartctl
  and nut_ups textfiles.
- `qga_disk_export_interval` — systemd timer `OnUnitActiveSec` value.
- `qga_disk_export_enabled` — gate; defaults true (every pve node can host
  running QEMU VMs, and the script handles zero running VMs gracefully).

## Wiring into Alloy

Nothing to do: the pve nodes already run Alloy with the textfile collector
enabled (reading the same directory for `smartctl.prom` / `nut_ups.prom`),
so a new `qga_disk.prom` in that directory flows to VictoriaMetrics with no
Alloy or scrape-config change.

## Where it's invoked

- `ansible/deploy_qga_disk_export.yml` — the narrow single-role playbook,
  `hosts: proxmox_nodes`.
- Mirrorered into `ansible/deploy_monitoring.yml`'s pve play (same gating
  style as `smartctl_exporter`) so a future full monitoring deploy
  converges the same state. Never run `deploy_monitoring.yml` just for
  this role — its first play recreates the monitoring CTs.

## Alert rules

`roles/grafana/templates/alerting_rules.yml.j2`, rule `disk_full`. Its
branch C (the `{fstype!~"tmpfs|overlay|squashfs|devtmpfs", instance!~"tc-.*",
mountpoint!~".*subvol-[0-9]+-disk-[0-9]+"}` OR-branch) is wrapped in a
second `label_replace` that overwrites `display` with `guest` when the
series carries a `guest` label, so an over-90% appliance filesystem alerts
under the guest's name. Series without a `guest` label (every other host's
node_exporter `node_filesystem_*`) keep the `display=instance` fallback —
the second `label_replace` is a no-op when the source label is absent.
