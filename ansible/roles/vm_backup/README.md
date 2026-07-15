# vm_backup

Encrypted VictoriaMetrics snapshot backup to Google Drive for vm-01.

## Architecture (hybrid tiered storage)

```
                    vm-01 (CT 106, 250G disk)
                    ┌─────────────────────────────┐
  Prometheus scrape │ VictoriaMetrics              │
  ────────────────► │ -retentionPeriod=2y          │ (~86G/2y)
                    │ /var/lib/victoria-metrics    │
                    └─────────────┬───────────────┘
                                  │ daily 03:00 CT
                                  ▼
                    ┌─────────────────────────────┐
                    │ vm-backup-daily.sh           │
                    │ 1. POST /snapshot/create      │
                    │ 2. rclone copy -L (encrypt)   │
                    │ 3. verify + delete local      │
                    │ 4. prune GDrive >90d           │
                    └─────────────┬───────────────┘
                                  ▼
                    ┌─────────────────────────────┐
                    │ gdrive:vm-backup/ (encrypted) │
                    │  daily/<ts>      (90d)        │ ← DR backup
                    │  archive-yearly/<year> (5y+) │ ← cold tier
                    └─────────────────────────────┘
```

- **2y queryable locally** in VM. Grafana charts the last 2y at full 15s resolution.
- **>2y archived to GDrive** as yearly snapshots (cold tier). Not directly queryable —
  restore to a scratch VM to query (see Restore below).
- **Daily snapshots** to GDrive with 90d retention = DR capability against disk/CT loss.
- **All data encrypted client-side** via rclone crypt (AES). Google only sees ciphertext.

## Why not 5y local?

VM can't tier to object storage while keeping data queryable — retention is a single
knob. 5y at ~43G/yr = 220G, which would fill the 250G disk. The hybrid (2y local +
archive-yearly to GDrive) keeps the local disk mostly empty while preserving 5y+ of
historical data in cold storage. To query data older than 2y, restore a yearly archive
to a scratch VM (see Restore).

## Services installed

| Unit | Schedule | Purpose |
|------|----------|---------|
| `victoriametrics-backup.timer` | daily 03:00 CT | snapshot + upload to `daily/`, 90d retention |
| `victoriametrics-archive-yearly.timer` | Jan 1 04:00 CT | full-dataset upload to `archive-yearly/<year>` |
| `victoriametrics-backup-watchdog.timer` | every 6h | alert if no successful backup in 36h (journal) |

## Secrets

Vault vars (in `ansible/group_vars/all/vault.yml`):
- `vault_vm_backup_gdrive_client_id` / `_client_secret` / `_token` — Google OAuth
  (reused from `media_gallery` GCP project "tg-harvester-03393"; full `drive` scope)
- `vault_vm_backup_crypt_password` / `_password2` — rclone crypt passwords (plaintext)
- `vault_vm_backup_crypt_password_obscured` / `_password2_obscured` — rclone-obscured forms

macOS keychain (second copy for recovery):
- `VMBackupGDriveToken`, `VMBackupGDriveClientId`, `VMBackupGDriveClientSecret`
- `VMBackupCryptPassword`, `VMBackupCryptPassword2`

### BLAST RADIUS

The OAuth client_id/secret are shared with the `media_gallery` remote (same GCP project).
A token stolen from vm-01 can read/write ANY folder in the user's Drive (full `drive`
scope), including destroying encrypted photos. Accepted posture for homelab. To narrow:
create a separate OAuth client + use `scope=drive.file`.

## One-time setup (already done)

1. Generated two crypt passwords with `openssl rand -base64 32`
2. Obscured them with `rclone obscure` for the rclone.conf
3. Reused the tg-harvester GDrive OAuth token (same Google account)
4. Added vault vars + keychain entries
5. Deployed the role to vm-01

## Restore procedure

### Restore daily backup (DR: disk failure, CT loss)

```bash
# On a fresh vm-01 (or scratch LXC with VM installed):
# 1. Stop VM
systemctl stop victoriametrics

# 2. Empty the data dir
rm -rf /var/lib/victoria-metrics/data /var/lib/victoria-metrics/indexdb

# 3. List available backups on GDrive
rclone --config /root/.config/rclone/rclone.conf lsd vmbackup_crypt:daily

# 4. Restore the most recent backup
rclone --config /root/.config/rclone/rclone.conf copy \
  vmbackup_crypt:daily/20260715T185749Z/ /var/lib/victoria-metrics/

# 5. Fix ownership (VM runs as victoriametrics user)
chown -R victoriametrics:victoriametrics /var/lib/victoria-metrics/

# 6. Start VM
systemctl start victoriametrics
```

### Restore yearly archive (query data older than 2y)

The cold tier is NOT directly queryable. To query archived data:

```bash
# 1. Provision a scratch VM instance (can be on any host with enough disk)
#    Use the victoriametrics role to install the binary.

# 2. Stop VM on the scratch instance
systemctl stop victoriametrics

# 3. List available yearly archives
rclone --config /root/.config/rclone/rclone.conf lsd vmbackup_crypt:archive-yearly

# 4. Restore the year you want to query
rclone --config /root/.config/rclone/rclone.conf copy \
  vmbackup_crypt:archive-yearly/2026/ /var/lib/victoria-metrics/

# 5. Start VM with a SHORT retention (just long enough to cover the archived year)
#    and on a different port (8429) so it doesn't conflict with prod
# Edit the systemd unit:
#   -retentionPeriod=2y -httpListenAddr=:8429
# Then start + query via Grafana (add a second datasource pointing at :8429).
systemctl start victoriametrics
```

### Restore test (run monthly)

```bash
# On vm-01, restore the latest daily to a temp dir + verify VM can read it:
TMP=$(mktemp -d)
rclone --config /root/.config/rclone/rclone.conf copy \
  vmbackup_crypt:daily/$(rclone --config /root/.config/rclone/rclone.conf lsd vmbackup_crypt:daily | tail -1 | awk '{print $NF}')/ $TMP/
ls -la $TMP/data/  # should show big/, small/, indexdb/ subdirs
# Query the restored snapshot directly (VM supports read-only query against a snapshot dir)
/usr/local/bin/victoria-metrics-prod -storageDataPath=$TMP -retentionPeriod=100y &
sleep 2
curl -s 'http://localhost:8428/api/v1/query?query=homeassistant_climate_current_temperature_celsius{entity="climate.ecobee_thermostat"}' | python3 -m json.tool
kill %1
rm -rf $TMP
```

## Verification

```bash
# Timers active
systemctl list-timers 'victoriametrics-*'

# Last backup success
cat /var/lib/vm-backup/last_success | xargs -I{} date -d @{}

# GDrive contents
rclone --config /root/.config/rclone/rclone.conf tree vmbackup_crypt:daily --max-depth 2
rclone --config /root/.config/rclone/rclone.conf lsd vmbackup_crypt:archive-yearly

# Backup logs
journalctl -u victoriametrics-backup.service -n 50
```