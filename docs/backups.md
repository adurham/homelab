# Backups — where every copy lives

Three tiers, on purpose: the on-site dump is fast to restore from, the
off-site copy survives the house, and the vault copy is a local second
generation that doesn't cost anything to read back.

| Tier | What | Where | Cadence | Retention |
| :-- | :-- | :-- | :-- | :-- |
| 1. On-site | `vzdump` snapshot of every guest | `/nvme-pool/vzdump-backups/dump` on each PVE node | nightly 02:00 / 02:30 / 03:00 (one job per node) | 3 daily + 2 weekly |

> The TanOS appliances (VMIDs 200-205, `ts-*`/`tms-*`/`tzs-*`) were added to
> the per-node jobs on 2026-11-08 after ts-01 was found with no restore point
> at all while it was down.
| 2. Off-site | newest archive per guest, rclone-crypt encrypted | `vmbackup_crypt:pve/` (Google Drive) | weekly, Sat 05:00, `pve-backup-push.timer` | newest 4 per guest |
| 3. Local second generation | newest archive per guest, staged copy | `/mnt/vault/pve-backups/<YYYYMMDD>/` on amd-workstation (8TB `vault`) | weekly, immediately after tier 2 (`ExecStartPost`) | ≤ 2 TiB, oldest generations pruned |

Tier 2 pushes through a staging dir (`/nvme-pool/pve-backup-stage` on pve01, the
same ZFS pool the guests live on). **The staging dir is empty between runs.**
Since 2026-11-15 `pve-backup-push.sh` works one archive at a time: fetch it,
`rclone copyto` it, delete it, and skip any archive Drive already holds with the
same name and size. Peak staging use is the largest single archive (~133 GiB,
ts-02), not a whole generation.

> **What was wrong before (found 2026-11-15):** the script staged the whole
> generation first and only pruned files older than a day at the end of the *next*
> run, so a full generation sat on the guest pool all week. Once the TanOS
> appliances joined the jobs (2026-11-08) that generation was **399 GiB, 43 % of
> pve01's 928 GiB pool**, in the pool's root dataset, where per-guest and
> per-dataset space checks never saw it. It was deleted by hand after every file
> was confirmed on Drive and in the vault with identical sizes.

Hardening added the same evening: a `flock` so a 40-hour run cannot overlap the next timer tick;
the staging dir is now its own ZFS dataset (`nvme-pool/pve-backup-stage`, 160 GiB quota) so a
half-fetched archive left by a mid-run fence can never exceed it and the space shows up in
`zfs list` (it was invisible in the pool's root dataset); leftovers are deleted at the start of
every run (a watchdog reset runs no trap); Drive pruning is gated **per guest** on that guest's
newest archive being on Drive, so one failing guest cannot freeze pruning for the rest; and the
`sort -t'\t'` in the prune step, which GNU sort rejects ("separator must be exactly one
character long"), is fixed. The original script had the same line, so Drive pruning could never
have worked. It had not mattered yet: Drive never held more than four copies of any guest. What
that line did to past runs (the unit's journal is volatile) was not established.

**Tier 3 is not automatic right now.** The `ExecStartPost` that copies the staging
dir to the vault is the drop-in
`/etc/systemd/system/pve-backup-push.service.d/vault-copy.conf.disabled`
(note the suffix: systemd ignores it) and neither it nor
`pve-backup-vault-push.sh` is in this repo. The `20261114` vault generation exists,
so it ran at least once. With the new per-file flow the staging dir is empty after
a push, so re-enabling tier 3 as it was would copy nothing; it needs reworking to
run per file (or against the node dumps directly) before it is turned back on.

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

## Restore drills

| Date | What | Result |
| :-- | :-- | :-- |
| 2026-11-09 | CT 105 (`ntp-01`) from the 2026-11-08 03:01 vzdump, restored to VMID 900 on pve03 `nvme-data`, net0 removed before boot to avoid an IP clash | PASS — booted as `ntp-01`, `/etc/chrony/chrony.conf` intact, `chrony` active; VMID 900 destroyed after the check |

## Restore drill, 2026-11-15 (the first one ever run)

Both restores were done into scratch guests with **no network interface** (VMIDs 8801/8802;
9000-9002 are templates) and destroyed afterwards.

| what | result |
|---|---|
| Drive -> crypt -> pve01: `vzdump-lxc-100` (authentik) 11-14, 5.3 GiB | 54 MiB/s, ~100 s; `zstd -t` clean |
| `pct restore` of it, no NIC, started | 13 GiB at 85 MiB/s; `is-system-running: running`, 0 failed units, 8 docker containers present |
| `pct restore` of `vzdump-lxc-140` (graf-db-01, on-site archive from 03:06), Postgres started by hand | Grafana DB has **109 alert rules; the live one has 122**. The 13 are exactly the pve-platform rules provisioned later that day. 16 dashboards, 2 users, authentik DB 12 users in both |

A restored Patroni member is a replica: its data dir carries `standby.signal`, which has to be
removed to start it standalone, and the restored CT config still carries the LIVE static IP and
MAC, so delete every `net*` before the first start or it collides with the real one.

**What the drill got wrong, and what it really showed (corrected the same evening)**

- It first looked as if the Drive crypt keys lived only on pve01. They do not: `rclone.conf` is
  rendered by Ansible from vaulted variables (`vault_vm_backup_gdrive_*`; the plaintext crypt
  passwords are also in the vault and the macOS keychain, per the template header), and the vault
  password is in 1Password. The rendered file was copied to 1Password anyway (Hermes vault,
  "rclone.conf (pve backup Drive + crypt keys)"): redundant, and it also holds a live full-Drive
  OAuth token, so delete the item if you would rather not have that there.
- **The "~16 Mbit/s, ~40 h per weekly push" figure was wrong.** The line is 1 Gbit symmetric and a
  1 GiB test upload from pve01 measured 21-27 MiB/s (single rclone stream; chunk size and stream
  count barely matter). The full weekly push is about 100 GiB, so ~1.2 h, not 40 h. The "fence
  killed a 40 h run" explanation for the missing Drive copies is therefore unsupported. Why 24
  guests had no Drive copy is not established; the reworked push covers all of them (31 archives,
  103 GiB planned).
- The owner decided only the **active** Tanium VMs need off-site copies (ts-01 = 200, tms-01 =
  202, assuming the -01 pair is active). So: the standby TanOS VMs (201/203/205, ~210 GiB of the
  old weekly push) are excluded from the push (`pve_backup_offsite_exclude_vmids`; they keep their
  nightly on-site vzdump), and ts-01/tms-01 go to Drive as **ZFS send streams**
  (`pve-tanium-offsite`, Sun 05:00): no vzdump of them is possible (120-190 GiB of space nobody
  has), and nothing is staged locally. Per VM: atomic snapshot of all zvols, `zfs send -c | rclone
  rcat`, uploaded size compared with bytes sent, config + sha256 manifest alongside, 2 generations
  kept, snapshot destroyed afterwards. Round-trip drilled with a 1 GiB scratch zvol (sha256 of the
  restored zvol equal). **Not drilled:** a full-size restore of ts-01/tms-01 (restore command is in
  the script header; expect ~1.6 h per 300 GiB at the 54 MiB/s measured download).
- Everything that read `pve_backup_push_last_success_timestamp_seconds` was a no-op: the metric was
  POSTed to an import endpoint nothing verified, and no rule used it. Both jobs now write
  node_exporter textfiles and `pve_offsite_push_stale`, `pve_tanium_offsite_stale` and
  `pve_tanium_offsite_missing` alert on them.
- The dead man's switch does exist and is not lab-mail-only: Grafana's always-firing
  `dead_mans_switch` pings healthchecks.io (contact point `healthchecks_dms`, policy repeat 5 m).
  What is not verified from here is what healthchecks.io does when the pings stop (who it
  notifies); that is configured on their side.
- tms-01/tzs-01 (and ts-01) were in no vzdump job. tzs-01 (204) still is, by decision. The
  2026-11-23 cleanup of `moved-20261115-vm-202-disk-*` on pve02 can wait for the first complete
  tms-01 stream (check `rclone lsf vmbackup_crypt:pve-zfs/`), after which tms-01 has an off-site copy.
