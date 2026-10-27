# Home Assistant backups — off-device, encrypted, 2026-10-27

## State before

HA's automatic backups were healthy: nightly at ~05:20, ~963-993 MB each, three
retained. But they lived only in `/backup` on the HAOS box — the same 28 GB SD
card (`/dev/mmcblk0p8`, 72% full) that holds the config and the 2.3 GB recorder
database. A card failure would have destroyed the hub and every backup of it in
one event. The backup config named a cloud agent, but no agent was registered,
so nothing ever left the device.

(The API field `last_successful_automatic_backup` reads empty and makes the
backup system look broken. It is not: the tarballs are on disk and a forced
manual backup completes normally in ~5 minutes.)

## What was built

`roles/ha_backup` + `deploy_ha_backup.yml`, running on **hermes-gw-01** — a host
HAOS already trusts, so no new device and no new network path:

1. Pulls `/backup/*.tar` from HAOS over the Advanced SSH add-on (port 2222) with
   a dedicated ed25519 key (`/root/.ssh/ha_backup`, public key appended to
   HAOS's `authorized_keys`, previous file backed up as
   `authorized_keys.bak-20261027`). scp per file, incremental — the add-on has
   no rsync.
2. Pushes them with rclone to the lab's existing **crypt** remote
   (`vmbackup_crypt:ha/` → Google Drive `vm-backup/ha`), the same client-side
   encrypted remote `roles/vm_backup` already uses. Google sees ciphertext and
   encrypted filenames.
3. Prunes both the staging dir and Drive at 14 days. HA itself keeps 3, so Drive
   is the longer history.
4. `ha-backup-push.timer`, daily at 06:15 America/Chicago (11:15 UTC on that
   host) — after HA's 05:20 backup, with `Persistent=true` so a missed run
   catches up.

## Verified

First run: `fetched 16 new, 0 already present`, then 16 objects / **3.718 GB** in
`vmbackup_crypt:ha/` (Drive), staging 3.8 GB, service exited clean in ~5 minutes
(37 s CPU). A single-file round trip was also tested first (upload → `rclone ls`
shows the decrypted name/size → delete) to prove the crypt path before moving
3.7 GB.

## Caveats

- The rclone OAuth client is shared with media_gallery (full `drive` scope) — the
  same accepted posture as `roles/vm_backup`. Fine for a homelab; narrow it with a
  dedicated OAuth client + `drive.file` scope if that ever matters.
- 14 days of HA backups in Drive is ~14 GB at current sizes.
- Restoring from Drive: `rclone copy vmbackup_crypt:ha/<file> /backup/` on the
  HAOS box (via the SSH add-on) then restore through the HA UI.
