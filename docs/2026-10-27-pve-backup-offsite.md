# Proxmox backups and VMs — coverage and off-site copy, 2026-10-27

## What existed

- On-site vzdump: 45 archives, ~126 GB across the three node dumps
  (pve01 98 GB/30, pve02 8.8 GB/6, pve03 19 GB/9), retention 3 daily + 2 weekly
  per guest, jobs at 02:00 / 02:30 / 03:00.
- Every archive sits on the **same NVMe pool that holds the guest disks**, so a
  device failure takes the guests and their backups together. There was no
  off-site copy of any Proxmox archive — only vm-01 had one, through its own
  GDrive job.
- VM coverage was containers-only. `ps5forge-rig` (240) and `mitm-generic` (241)
  had a single manual archive from 2026-10-26 and nothing scheduled; the Tanium
  rigs (200-205), the stopped win-*/bnp-* case VMs and the templates had none.

## What changed

1. **VM coverage (done earlier today):** 240 and 241 added to the nightly job's
   union vmid list, applied through `deploy_pve_backup_jobs.yml` on all three
   nodes. Proved with manual snapshot backups: VM 240 in 15 s (356 MB), VM 241 in
   ~30 s (1.5 GB), no downtime.
   The remaining VMs stay out on purpose — Tanium test rigs and stopped case VMs
   are rebuilt from templates 9000-9002.
2. **Off-site copy — `roles/pve_backup_offsite`** on pve01 (Proxmox's cluster root
   keys already give it SSH to pve02/pve03, so no new trust):
   - stages the newest archive of every guest (both `.tar.zst` containers and
     `.vma.zst` VMs) from all three nodes into `/nvme-pool/pve-backup-stage`;
   - pushes them with rclone through the encrypted crypt remote to
     `drive:vm-backup/pve`;
   - Drive keeps 28 days, staging files are deleted after a day (the on-site dump
     remains the source of truth, so the pool doesn't accumulate generations);
   - `pve-backup-push.timer`, Saturdays 05:00 America/Chicago, catch-up enabled.

## Numbers

- One generation (newest per guest, all nodes) ≈ **43 GB** across 20 archives.
- Observed upload rate from pve01 ≈ 2 MB/s (~16 Mbit/s), so a full baseline is
  ~6 hours. The first run was stopped deliberately mid-upload to avoid saturating
  the uplink during the day; the Saturday timer completes the baseline from the
  already-staged files.
- The Drive account is a 5 TB plan with **2.82 TB free** — the 200 GB
  `vm_backup_max_total_gb` ceiling in `roles/vm_backup` is a policy limit, not a
  quota. The encrypted tree currently holds 196 GB (192 GB of VictoriaMetrics
  daily snapshots + 3.7 GB of Home Assistant).

## Still open

- Restore from Drive has not been exercised (same class of gap as the earlier
  LXC restore drill): `rclone copy vmbackup_crypt:pve/<archive> /nvme-pool/vzdump-backups/dump/`
  then `pct restore` / `qm restore`.
- 43 GB/week of upstream is a real cost at ~16 Mbit/s. If that hurts, options are
  fortnightly cadence, or excluding the two largest guests (hermes-gw-01 16.8 GB,
  frigate-01 8.1 GB) and keeping only config-level guests off-site.
