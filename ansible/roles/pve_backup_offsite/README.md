# pve_backup_offsite

Off-site copies of the Proxmox backups, run from pve01 through an rclone **crypt** remote on Google
Drive (file names and contents are encrypted client-side). The full picture, retention and the restore
drill results are in [`docs/backups.md`](../../../docs/backups.md); this file is the role's own summary.

| Job | Script (on pve01) | Timer | What it sends | Drive path |
| :-- | :-- | :-- | :-- | :-- |
| general push | `/usr/local/sbin/pve-backup-push.sh` | `pve-backup-push.timer`, Sat 05:00 | newest vzdump archive per guest from all three nodes, except `pve_backup_offsite_exclude_vmids` | `vmbackup_crypt:pve/` |
| active Tanium VMs | `/usr/local/sbin/pve-tanium-offsite.sh` | `pve-tanium-offsite.timer`, Sun 05:00 | ZFS send streams of `pve_tanium_offsite_vmids` (ts-01 = 200, tms-01 = 202), config, sha256 manifest | `vmbackup_crypt:pve-zfs/` |

## Variables worth knowing

- `pve_backup_offsite_exclude_vmids` (default `[201, 203, 205]`): standby Tanium VMs not pushed.
- `pve_tanium_offsite_vmids` (default `[200, 202]`): the **active** Tanium pair. Change it if the active
  side ever flips.
- `pve_tanium_offsite_keep` (default 2), `pve_backup_offsite_keep_copies` (default 4): generations kept
  on Drive.
- `pve_backup_offsite_hc_push_url` / `pve_backup_offsite_hc_tanium_url`: optional healthchecks.io ping
  URLs; set them from the vault in `group_vars`, never in this role. Written to
  `/etc/pve-backup-heartbeat.conf` (0600) only when set.
- The rclone config (`rclone.conf.j2`) is rendered from vaulted variables; do not hand-edit the file on
  pve01 and do not run the whole role casually over a working config: it overwrites the Drive OAuth
  token with the vaulted copy.

## Operating notes

- Both scripts take a lock and exit 0 if another run is in progress; both clean up after a run that
  died. `DRY_RUN=1 pve-backup-push.sh` prints the plan; `MAX_MIB=N` limits it to small archives for a
  test; `pve-tanium-offsite.sh drill` (optionally `DRILL_NODE=pve02`) round-trips a 1 GiB scratch zvol.
- Measured 2026-11-15: one rclone stream does 21-27 MiB/s up and 54 MiB/s down on the 1 Gbit line.
- Metrics (node_exporter textfiles): `pve_backup_push_last_success_timestamp_seconds`,
  `pve_tanium_offsite_last_success_timestamp_seconds{vmid}`; alert rules `pve_offsite_push_stale`,
  `pve_tanium_offsite_stale`, `pve_tanium_offsite_missing` (roles/grafana, pve-platform group).
