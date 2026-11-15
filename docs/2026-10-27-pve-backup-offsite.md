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

## Update 2026-11-15 — the "43 GB generation" is now ~300 GiB

The TanOS appliances joined the nightly jobs on 2026-11-08 (ts-02 130 GiB, tms-02 42 GiB,
tzs-02 22 GiB, plus ts-01 111 GiB when it has an archive), and vm-01 is 41 GiB. One
generation is now **~300 GiB of new data per week** (the dry run on 11-15 listed 42
archives, 299 GiB), not 43 GB. Two consequences, both fixed in
`roles/pve_backup_offsite`:

- Staging held the whole generation until the next week's run: 399 GiB on pve01's guest
  pool (see `docs/backups.md`). Now one archive at a time, empty between runs.
- The push compared files by modtime, and every staged copy has a fresh mtime, so an
  unchanged archive (ts-01's 111 GiB, which no job refreshes) would be re-uploaded every
  week. Now skipped by name + size.

What this does **not** fix: ~300 GiB a week is still a lot of upstream. The uplink was
measured at ~16 Mbit/s (~2 MB/s), which is ~40 hours for 300 GiB, longer than the weekly
cadence leaves room for if the runs overlap. Excluding the three Tanium VMs from the
off-site push (they are rebuildable and have weekly ZFS snapshots on-site), or pushing them
monthly, would cut it to ~90 GiB. That is a decision, not a change made here.

## Still open

- Restore from Drive has not been exercised (same class of gap as the earlier
  LXC restore drill): `rclone copy vmbackup_crypt:pve/<archive> /nvme-pool/vzdump-backups/dump/`
  then `pct restore` / `qm restore`.
- 43 GB/week of upstream is a real cost at ~16 Mbit/s. If that hurts, options are
  fortnightly cadence, or excluding the largest guests (frigate-01 8.1 GB and the
  TanOS appliance VMs) and keeping only config-level guests off-site.
