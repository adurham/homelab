# Disaster recovery runbook — rebuilding the lab from encrypted Google Drive

Written 2026-10-27, after the off-site push went live. **Status: the off-site
path is partly proven** — see "What has actually been proven" below. The parts
still marked UNTESTED are exactly that.

## What has actually been proven (2026-10-27)

- **Vault-only access to the off-site copies, from outside the cluster.** On a
  laptop with no cluster credentials, rendering the rclone config from the
  Ansible vault alone was enough to list both remotes: 16 objects under `ha/`,
  19 under `pve/`, filenames decrypting correctly. The crypt password and OAuth
  token therefore survive without any cluster host.
- **Download + decrypt an HA backup.** Pulled one archive from `ha/` onto the
  laptop, decrypted its name, and `tar -tf` listed its contents (`backup.json`,
  `core_configurator.tar.gz`). Home Assistant's backups are **plain tar, not
  encrypted** — the rclone crypt layer is the only encryption protecting them.
  There is no separate HA backup key to lose.
- **Restore an archive pulled back from Drive, and boot it.** `pve-restore-verify`
  does this monthly on pve01: fetch the smallest object from `pve/`, restore to
  throwaway VMID 998, strip NICs, boot, check userspace, destroy. Passed twice
  (17 s and 19 s, 14 running units).

Still unproven: any **VM/VMA** restore (the qemu path has never been restored,
on-site or off-site), authentik (the dependency root), vm-01 from its own
`daily/` snapshots, an HA restore end-to-end, and — the one thing no drill can
prove — that the vault password itself is recoverable if this laptop and all
three nodes are gone at once.

## What exists off-site

| Remote path | Contents | Cadence | Retention |
|---|---|---|---|
| `vmbackup_crypt:pve/` | newest vzdump archive of each of the 17 production guests (`.tar.zst` for LXCs, `.vma.zst` for VMs) | weekly, Sat 05:00 | 28 days |
| `vmbackup_crypt:ha/` | Home Assistant's own nightly backups | daily 06:15 | 14 days |
| `vmbackup_crypt:daily/`, `archive-yearly/` | VictoriaMetrics snapshots (vm-01 self-backup) | daily | role-defined |

The Google account is 5 TB, ~2.1 TB used. The crypt remote is `vmbackup_crypt:`
with an underlying `vmbackup_drive:` remote; both are rendered from
`roles/vm_backup/templates/rclone.conf.j2`.

## What you need before starting

1. **The vault password** — lives in 1Password, not in the repo. Without it the
   rclone config cannot be rendered and the crypt remote is unreadable.
2. **Repo access** (`adurham/homelab`) — the inventory is the source of truth for
   hostnames, IPs and VMIDs (`ansible/inventory/proxmox.yml`).
3. A host with rclone and ~60 GB of free space for staging.

## Rebuild order

### 1. Proxmox base

Install Proxmox VE on the replacement hardware, then set hostname/IP per
`ansible/inventory/proxmox.yml`. The three nodes are `pve01` .11, `pve02` .12,
`pve03` .13. Keep the same kernel line the fleet was last proven on — at the time
of writing that is `7.0.14-24` (the `-24` hold exists for the pve01 NIC-stall
incident; see `docs/2026-10-27-pve01-nic-stall-and-kernel-revert.md`).

Storage layout to recreate on each node (names matter — guest configs reference
them):

- `nvme-data` — zfspool, holds every guest disk (`subvol-<vmid>-disk-1`,
  `vm-<vmid>-disk-0`)
- `vzdump-nvme` — dir storage for archives, on the same pool
- `local-lvm` — exists but is unused (0 %)

### 2. Get the archives down

```bash
# on the new host, with the vault password available
mkdir -p /root/.config/rclone
# render roles/vm_backup/templates/rclone.conf.j2 with the vault vars, mode 600
rclone copy vmbackup_crypt:pve/ /nvme-pool/vzdump-backups/dump/ --transfers 2
```

### 3. Restore the guests

Per LXC (verified working on-site):

```bash
pct restore <vmid> /nvme-pool/vzdump-backups/dump/vzdump-lxc-<vmid>-<stamp>.tar.zst \
    --storage nvme-data
sed -i '/^net[01]:/d' /etc/pve/lxc/<vmid>.conf   # only if restoring alongside a live copy
pct start <vmid>
```

Per VM (UNTESTED — the qemu path has never been restored):

```bash
qm restore <vmid> /nvme-pool/vzdump-backups/dump/vzdump-qemu-<vmid>-<stamp>.vma.zst \
    --storage nvme-data
qm start <vmid>
```

Restore order (each depends on the one before):

1. `dns-01` 102 — everything resolves through it
2. `tailscale-gw` 101 and `proxy-01` 108 — remote access
3. `authentik` 100 — SSO
4. `lb-01` 103 — front door for the web services
5. `graf-01` 107, then the VM/Loki box — so you can see what you are doing
6. `mail-01` 104, `ntp-01` 105, `hermes-gw-01` 113, `bwt-dhcp` 114
7. `tg-harvester-01` 115, `media-ingest-01` 116, `media-ingest-02` 117,
   `adblock-proxy-01` 118, `frigate-01` 170
8. VMs `ps5forge-rig` 240, `mitm-generic` 241

`vm-01` (106) is not in the vzdump set — restore it from its own
`vmbackup_crypt:daily/` snapshots.

### 4. Home Assistant

The HA box is independent of the cluster. Its backups are in
`vmbackup_crypt:ha/`; copy one back to the box's `/backup` and restore through the
Supervisor (`ha backups restore <slug>` or the UI). Its config, add-ons and
database are all inside that tarball.

### 5. Verify before declaring done

- `pct list` / `qm list` on each node: every guest running
- `dig @172.16.0.10 …` resolves, `curl -k https://172.16.0.30` answers
- Grafana shows all scrape targets up; `probe_success == 0` only for the Tanium
  standby VMs
- Each restored guest: `systemctl is-system-running` == `running`, no failed units
- The two push pipelines run once by hand and log a fresh success timestamp

## What is deliberately not recoverable

- Tanium rigs 200-205, `usda-*`, `win-*`, `bnp-*` and the `tc-*` container fleet —
  rebuilt from templates 9000-9002, never backed up
- Templates themselves — rebuild from the original ISOs
- Secrets: the Ansible vault (1Password) and the rclone OAuth token are the two
  things whose loss makes the rest of this document useless. Both live outside the
  cluster on purpose.

## The drill that closes the gap

Once, in a quiet window: pull one archive back from Drive to a throwaway storage,
restore it to an unused VMID, boot it with NICs stripped, confirm
`system-is-running == running`, then destroy it. That proves the crypt remote, the
download path and the archive in one pass. Until then, the off-site copy is a
backup only in the sense that it exists.
