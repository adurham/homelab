# roles/proxmox_storage

Cluster-wide Proxmox storage configuration. Runs only on the first
proxmox node (`groups['proxmox_nodes'][0]`) — `pvesm` writes to
`pmxcfs` so the change propagates to the rest of the cluster
automatically.

## What it does

- Adds the cluster-wide ZFS-pool storage backing for CTs/VMs.
  Backing pool: `nvme-pool` (per-node NVMe ZFS pool, created here via
  `zpool create`; the role installs `zfsutils-linux` first). Registered
  in Proxmox as the `nvme-data` zfspool storage (`storage` defaults:
  `zfs_pool_name: nvme-pool`, `zfs_disk_device: /dev/nvme0n1`,
  `zfs_storage_id: nvme-data`).
- Enables + starts the monthly ZFS scrub timer
  (`zfs-scrub-monthly@{{ zfs_pool_name }}.timer`), with a per-node
  `OnCalendar` override staggered by `zfs_scrub_day_of_month`
  (1-28; set per host in `inventory/proxmox.yml` — pve01=1, pve02=8,
  pve03=15) so a 3-node cluster doesn't scrub simultaneously.
- Creates a `dir`-type storage (`vzdump-nvme`, var
  `pve_backup_zfs_storage_id`) at `/<pool>/vzdump-backups` with
  `content=backup`, so vzdump archive files land on the ZFS pool
  instead of the small root disk. A `zfspool` storage can't hold backup
  content, which is why this is a separate `dir` storage (see the
  2026-09-12 incident comment in `tasks/main.yml`).

Note: the zpool itself is created on every node; the two `pvesm`/`zfs
create` storage registrations are `run_once`/`delegate_to` the first
cluster node, so they run once for the whole cluster.

## Where it's invoked

`deploy_proxmox.yml` (Proxmox cluster bring-up), after `proxmox_common` /
`proxmox_network`. Idempotent on re-apply: `pvesm` returns the existing
config without modification if the storage already exists.
