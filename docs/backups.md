# Backups — where every copy lives

Three tiers, on purpose: the on-site dump is fast to restore from, the
off-site copy survives the house, and the vault copy is a local second
generation that doesn't cost anything to read back.

| Tier | What | Where | Cadence | Retention |
| :-- | :-- | :-- | :-- | :-- |
| 1. On-site | `vzdump` snapshot of every guest | `/nvme-pool/vzdump-backups/dump` on each PVE node | nightly 02:00 / 02:30 / 03:00 (one job per node) | 3 daily + 2 weekly |
| 2. Off-site | newest archive per guest, rclone-crypt encrypted | `vmbackup_crypt:pve/` (Google Drive) | weekly, Sat 05:00, `pve-backup-push.timer` | newest 4 per guest |
| 3. Local second generation | newest archive per guest, staged copy | `/mnt/vault/pve-backups/<YYYYMMDD>/` on amd-workstation (8TB `vault`) | weekly, immediately after tier 2 (`ExecStartPost`) | ≤ 2 TiB, oldest generations pruned |

Tier 2 and 3 both start from the same staging dir
(`/nvme-pool/pve-backup-stage` on pve01), which is pruned one day after a
run — that is why tier 3 is an `ExecStartPost` of the push unit and not an
independent timer.

## Tier 3 — the 8TB vault copy

- `pve-backup-vault-push.sh` (pve01, `/usr/local/sbin/`) rsyncs the staging
  dir to `adam.durham@192.168.86.19:/mnt/vault/pve-backups/<YYYYMMDD>.part/`,
  renames it to `<YYYYMMDD>` only after a clean rsync, then calls
  `~/.local/bin/vault-prune.sh` on the workstation.
- SSH trust: root@pve01 → adam.durham@amd-workstation with
  `/root/.ssh/id_vaultpush`, restricted to `from="192.168.86.11"` in
  `~/.ssh/authorized_keys` on the workstation.
- `vault-prune.sh` keeps the newest generations until the 2 TiB cap and
  never deletes the newest one. It only ever touches dated dirs under
  `/mnt/vault/pve-backups`.
- Metrics pushed to VictoriaMetrics from pve01 (writes from the workstation
  to `:8428/api/v1/import/prometheus` are accepted but do not land — use a
  PVE node):
  - `pve_backup_vault_last_success_timestamp_seconds`
  - `pve_backup_vault_bytes`
  - `pve_backup_vault_generations`

## Verify

```bash
# tier 1 — last night's jobs
ssh root@pve01 "pvesh get /nodes/pve01/tasks --typefilter vzdump --limit 3"

# tier 2 — last successful push
ssh root@pve01 "systemctl status pve-backup-push.service --no-pager | head -5"
curl -sG http://172.16.0.42:8428/api/v1/query \
  --data-urlencode 'query=pve_backup_push_last_success_timestamp_seconds'

# tier 3 — generations on the vault
ssh root@pve01 'ssh -i /root/.ssh/id_vaultpush adam.durham@192.168.86.19 "ls -1 /mnt/vault/pve-backups; du -sh /mnt/vault/pve-backups"'
```

## Restore

Tier 1/3: copy the archive to a node's dump dir and
`qmrestore <archive> <new-vmid>` / `pct restore <new-vmid> <archive>`.
Restore to a **new** VMID first — never overwrite the running guest.

Tier 2 (Google Drive): `rclone copy vmbackup_crypt:pve/<archive> /tmp/`,
then restore as above. The remote is `vmbackup_crypt` in
`/root/.config/rclone/rclone.conf` on pve01; the crypt passwords are
vaulted in this repo (`vault_vm_backup_crypt_password`) and in the macOS
keychain (`VMBackupCryptPassword`). Note: the push script's header says
"Managed by Ansible — roles/pve_backup_offsite", but that role is not in
this repo — the live unit + script are hand-maintained on pve01.
