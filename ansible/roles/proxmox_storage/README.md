# roles/proxmox_storage

Cluster-wide Proxmox storage configuration. Runs only on the first
proxmox node (`groups['proxmox_nodes'][0]`) — `pvesm` writes to
`pmxcfs` so the change propagates to the rest of the cluster
automatically.

## What it does

- Adds the cluster-wide ZFS-pool storage backing for CTs/VMs.
  Backing pool: `nvme-data` (per-node NVMe ZFS pool created by
  `roles/proxmox_common`).
- No per-node tasks — runs once per cluster.

## Where it's invoked

`deploy_proxmox.yml` (Proxmox cluster bring-up). Idempotent on
re-apply: `pvesm` returns the existing config without modification if
the storage already exists.
