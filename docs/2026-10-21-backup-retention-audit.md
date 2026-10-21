# 2026-10-21 — vzdump retention audit, integrity check, restore readiness

Read-only audit of the nightly vzdump chain. Nothing was deleted, restored or
reconfigured live. Every number below comes from command output on
2026-10-21 (~13:00 CDT). pve03 was only queried through the cluster API
(`pvesh get /nodes/pve03/...` run from pve01), because it was under
post-reboot observation.

## 1. Jobs (`pvesh get /cluster/backup`)

| job id | node | schedule | storage | retention | vmid list |
|---|---|---|---|---|---|
| 41c3b19b-… | pve01 | Mon..Sun 02:00 | vzdump-nvme | keep-last=3 | 100,101,102,103,104,105,107,108,113,114,115,116,117,118,170 |
| 08bcc363-… | pve02 | Mon..Sun 02:30 | vzdump-nvme | keep-last=3 | same |
| 52cb07d6-… | pve03 | Mon..Sun 03:00 | vzdump-nvme | keep-last=3 | same |

All three jobs are node-scoped and carry the same union list, so each guest
is backed up once, by the node that hosts it that night. This is the
2026-10-03 fix. All three use zstd, snapshot mode and `mailnotification
always`. `vzdump-nvme` is a node-local `dir` storage (`shared 0`) at
`/nvme-pool/vzdump-backups`, so an archive exists only on the node that
made it.

Newest archive per guest (all from 2026-10-21 nightly runs, all tasks `OK`):

| vmid | name | HA | node | newest archive | size |
|---|---|---|---|---|---|
| 100 | authentik | yes | pve03 | 2026_10_21-03_00_04 | 5.30 GB |
| 101 | tailscale-gw | yes | pve01 | 2026_10_21-02_00_00 | 0.60 GB |
| 102 | dns-01 | yes | pve03 | 2026_10_21-03_03_05 | 0.45 GB |
| 103 | lb-01 | yes | pve01 | 2026_10_21-02_00_16 | 0.49 GB |
| 104 | mail-01 | yes | pve01 | 2026_10_21-02_00_33 | 0.44 GB |
| 105 | ntp-01 | yes | pve03 | 2026_10_21-03_03_20 | 0.43 GB |
| 107 | graf-01 | yes | pve01 | 2026_10_21-02_00_50 | 2.97 GB |
| 108 | proxy-01 | yes | pve01 | 2026_10_21-02_02_03 | 0.44 GB |
| 113 | hermes-gw-01 | yes | pve01 | 2026_10_21-02_02_21 | 16.90 GB |
| 114 | bwt-dhcp | no | pve01 | 2026_10_21-02_10_16 | 0.22 GB |
| 115 | tg-harvester-01 | no | pve02 | 2026_10_21-02_30_00 | 1.42 GB |
| 116 | media-ingest-01 | no | pve02 | 2026_10_21-02_30_31 | 0.59 GB |
| 117 | media-ingest-02 | no | pve01 | 2026_10_21-02_10_25 | 2.75 GB |
| 118 | adblock-proxy-01 | yes | pve01 | 2026_10_21-02_13_20 | 0.80 GB |
| 170 | frigate-01 | yes | pve01 | 2026_10_21-02_13_45 | 15.16 GB |

Running guests with no vzdump archive:

- **106 vm-01**: HA-managed and running. It is excluded on purpose because
  it has its own encrypted GDrive DR (roles/vm_backup). This is the only
  HA guest without an archive.
- **Running QEMU VMs 200–205 and 270–272** (ts/tms/tzs/bnp lab VMs): not HA,
  never in any job, no archive anywhere. Each has a 500 GB–1 TB virtual
  disk (vm-200-disk-1 alone is 113G on pve01), so vzdump on these pools is
  not viable anyway. This is an **open question for the owner**: confirm
  that they are disposable.
- Running tc-* LXCs: excluded by design (disposable test fleet).

`pvesh get /cluster/backup-info/not-backed-up` agrees: none of the 15
production LXCs appear in it.

## 2. Space

pve01 `/nvme-pool/vzdump-backups/dump`:

- 88 files totalling 121,010,345,420 B (112.70 GiB). 30 archives, 3 per guest for 10 guests.
- Oldest file is 2026-10-19 02:00 (103), newest is 2026-10-21 02:19 (170.log).
  There are 0 root-level (old-layout) files.
- The two big guests dominate: 113 has 3 archives at 46.99 GiB, 170 has 3 at
  42.48 GiB. The other 8 guests together hold 23.2 GiB.
- One full generation (newest archive of every guest pve01 hosts) is
  **37.99 GiB**.
- Duplicate: two manual CT 101 runs on 2026-10-20 (11:43 and 11:47) each
  took a keep-last slot. As a result, 101's oldest restore point on pve01 is
  only ~14 h old.
- Pool `nvme-pool` is 928G with 753G alloc, 175G free, 81% CAP and 68% FRAG.
  The dataset shows 147G avail. `vzdump-backups` uses 113G, has
  compressratio 1.00x, and has no quota.

pve02 holds 66 files, 13.48 GiB. Of that, **7.10 GiB (47 files) is orphan
archive groups** for 101/102/103/105/108. Those guests migrated away, so no
job will ever prune these files again. The newest of them dates from
2026-09-29 to 2026-10-04, except 101 on 10-20. On top of that, there is a
0.89 GiB partial `vzdump-lxc-115-2026_09_30-02_32_00.tar.dat` left by the
2026-09-30 run that ended "unexpected status". PVE does not track it (22
tracked volumes). **About 8 GiB on pve02 can only be reclaimed by hand.** I
did not delete it.

pve03 has 9 archives totalling 17.08 GiB (100/102/105 × 3), with 276 GiB avail.

### What a policy can reclaim

Retention cannot shrink pve01 much at steady state. One generation is 38 GiB,
and keeping at least 2 generations is the floor for a single-copy, on-node
backup. I simulated each policy against PVE's prune algorithm
(`prune_mark_backup_group`) on nightly runs:

| policy | archives/guest | oldest restore point | pve01 steady state |
|---|---|---|---|
| keep-last=3 (current) | 3 | always 2 d | ~114 GiB |
| **keep-daily=2,keep-weekly=1** | 3 | 2–8 d | ~114 GiB |
| keep-daily=3,keep-weekly=1 | 4 | 3–9 d | ~152 GiB (+38) |
| keep-daily=7 | 7 | 6 d | ~266 GiB (+152): does not fit |
| keep-last=3,keep-daily=7,keep-weekly=2 | 12 | 17–23 d | ~456 GiB (+342): does not fit |

`pvesm prune-backups vzdump-nvme --dry-run 1 --keep-daily 2 --keep-weekly 1`
on pve01 today would mark 10 archives = **36.72 GiB** for removal (all the
10-19 copies plus the extra manual 101). That reclaim is temporary: it
refills to 3 per guest by the next ISO week. On pve02 it would mark 6.

The real space levers are outside retention, so they are listed here but not
acted on:

1. **frigate-01's archive is 55.5% dead weight.** In its 10-21 tar,
   `var/lib/containerd.corrupt-20260728` and `…corrupt-20260816-185405` hold
   16.09 GB of the 28.98 GB of tar content. The live `var/lib/containerd` is
   7.26 GB. The `du` numbers are 5.2G and 4.2G. Removing those two
   leftover dirs inside the CT should cut each 15 GB nightly archive by
   roughly half: about 20+ GiB across 3 generations on pve01, and the same
   amount off the CT's subvol and its replicas. This is a guest change and
   needs the owner's OK.
2. Remove the pve02 orphan groups plus the `.tar.dat` (8 GiB). Follow
   `references/pve-vzdump-layout-orphans.md`-style gating.

## 3. Policy

**Recommended: `prune-backups keep-daily=2,keep-weekly=1`**, encoded in
`ansible/roles/proxmox_backup_jobs/defaults/main.yml`
(`pve_backup_prune_backups`). The role now also drift-corrects
prune-backups on existing jobs and asserts it after the write. Before this
change, it set retention only at job *creation*.

Why this policy:

- It costs the same disk as today, so it fits the 147G avail.
- It extends the oldest restore point from a fixed 2 days to as much as 8.
- Manual same-day runs no longer evict a whole night.

Apply it live. This writes `/etc/pve/jobs.cfg`, so it **needs approval
first**. Run it from the MacBook:

```bash
cd ~/repos/homelab/ansible
ansible-playbook deploy_pve_backup_jobs.yml --vault-password-file .vault_pass
```

Or use the equivalent raw commands on any node:

```bash
for id in 41c3b19b-20ea-4ba0-b760-52a79d1cb83a 08bcc363-a9bf-4de3-9c73-5c4581cc0b78 52cb07d6-1400-4437-9591-568cad479879; do
  sudo pvesh set /cluster/backup/$id --prune-backups keep-daily=2,keep-weekly=1 </dev/null
done
sudo pvesh get /cluster/backup --output-format json </dev/null   # verify prune-backups on all three
```

**When to apply:** between Mon 03:30 and Tue 02:00. In simulation, a first
run on a Tuesday never dips below 3 archives per guest. Applied on any other
day, the first night prunes to 2 per guest and stays there for 1–5 nights,
until the Monday week-rollover adds the third. That is still within policy,
but it is less protection for those days. This is why I did not apply it
today (Wednesday).

## 4. Integrity (pve01, `nice -n19 ionice -c3`, read-only)

| archive | size | `zstd -t` | `zstd -dc \| tar -tf` full walk | tar stderr |
|---|---|---|---|---|
| vzdump-lxc-114-2026_10_21-02_10_16 (bwt-dhcp) | 218,313,883 B | rc=0, 0.96 s | rc=0/0, 23,941 entries, 0.92 s | 0 B |
| vzdump-lxc-113-2026_10_21-02_02_21 (hermes-gw-01) | 16,904,515,437 B | rc=0, 43.5 s | rc=0/0, 679,766 entries, 45.6 s | 0 B |

- **First entries.** Both archives start with `./etc/vzdump/pct.conf` and
  `./etc/vzdump/pct.fw` (uid 65534), then the rootfs tree. The embedded
  pct.conf matches the live config (hostname, net0, rootfs size, 113's
  `/dev/net/tun` mount entry). `pvesh get /nodes/pve01/vzdump/extractconfig`
  also returns 114's config, which proves PVE's own restore-side parser
  reads it.
- **.log files.** Both show `Finished Backup` with no WARN or ERROR. 114
  wrote 690 MiB at 80 MiB/s in 9 s. 113 wrote 38 GiB at 82 MiB/s in 7m55s.
  Each log shows retention working (`pruned 1 backup(s)`, i.e. the
  2026-10-18 copy).
- **.notes files.** Both contain `ansible-managed nightly backup`.
- **Other logs.** 170's log has one benign line, `waiting for active
  replication or other operation..`. The manual 101 runs have no `.notes`,
  which is expected because manual runs don't use the job's template.
- **Errors.** None. Note that this proves the zstd frames and the tar
  structure are intact. It does not prove that the guest boots. Only a
  restore proves that (see §5).

## 5. Restore readiness

Rules:

- Restore on **the node that holds the archive**, since `vzdump-nvme` is
  node-local.
- Use a scratch vmid in **990–999**. `pvesh get /cluster/nextid --vmid 990`
  and `--vmid 999` both returned the id as free, and no zfs dataset, conf or
  replication entry uses 99x. Avoid 109/110: `vm-110-recovery` exists on
  pve01.
- Set the hostname to `restore-test-<vmid>`.
- Never add the scratch CT to HA or replication.
- Keep it out of the 02:00–03:30 backup window.
- Destroy it within 6 h: `guest_backup_missing` only excludes `tc-*` and
  `vm-01`, so a scratch CT that lives longer will page.

The archive's net0 carries the production static IP and MAC. **Always
override net0**, or the scratch CT will collide with the live guest.

Example: bwt-dhcp (114) restored onto pve01.

```bash
N=990; ARCH=vzdump-nvme:backup/vzdump-lxc-114-2026_10_21-02_10_16.tar.zst
sudo pvesh get /cluster/nextid --vmid $N </dev/null            # must echo $N
sudo pvesh get /nodes/$(hostname)/vzdump/extractconfig --volume $ARCH </dev/null   # inspect first
zfs list -H -o avail nvme-pool                                   # space gate (below)
sudo pct restore $N $ARCH --storage nvme-data --unique 1 \
  --hostname restore-test-$N --onboot 0 --start 0 \
  --net0 name=eth0,bridge=vmbr0,link_down=1 </dev/null
sudo pct start $N </dev/null && sudo pct exec $N -- systemctl is-system-running </dev/null
sudo pct exec $N -- ls / </dev/null                              # spot-check content
# teardown
sudo pct stop $N </dev/null; sudo pct destroy $N --purge 1 --destroy-unreferenced-disks 1 </dev/null
zfs list -H -o name | grep -- "-$N-" ; ls /etc/pve/nodes/*/lxc/$N.conf  # both must be empty
```

What the space gate needs to cover: the restored subvol's *used* size, not
the `size=` quota (subvols are sparse). Measured used sizes:

| guest | rootfs refer | raw tar size | archive |
|---|---|---|---|
| 113 | 22.0G | 38 GiB | 15.7G |
| 170 | 17.8G (1.60x) | ~27 GiB | 15.2G |
| 114 | 342M (2.12x) | 690 MiB | 208 MB |

So a "15 GB" restore means about 15–23 GB of new pool usage. The archive is
read in place, with no temp copy, because it is already on a dir storage on
the same pool.

**Go/no-go for a 15 GB restore (using a 23 GB worst case):**

| node | avail now | after restore | verdict |
|---|---|---|---|
| pve01 | 147G (pool 81% CAP, 68% FRAG) | ~124G, ~84% CAP | **GO**, outside 02:00–03:30. Destroy it the same day: ZFS at 85%+ with 68% FRAG slows allocation, and nightly vzdump briefly needs +15.7G while it writes 113's new archive before pruning the old one. |
| pve02 | 327G (61% CAP) | ~304G | **GO.** This is the most headroom. It is the best target if an archive is copied there for a test. |
| pve03 | 276 GiB (296,746,164,224 B) | ~253 GiB | **GO on space, NO-GO today** because the node is under post-reboot observation. |

This procedure has **not been executed** in this audit (no restores was a
hard rule). The last real restore test was 2026-09-10 (Authentik). The next
step is to run the 114 example above on pve01 or pve02.
