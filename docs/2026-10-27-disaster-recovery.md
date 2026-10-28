# Disaster recovery runbook — rebuilding the lab from encrypted Google Drive

Written 2026-10-27, after the off-site push went live. **Status: the whole
off-site path is proven** — Drive pull, decrypt, VM restore, LXC-with-database
restore, a full Home Assistant restore and a metrics-archive replay have all
been run end to end; see "What has actually been proven" below.

## What has actually been proven (2026-10-27)

- **Vault-only access to the off-site copies, from outside the cluster.** On a
  laptop with no cluster credentials, rendering the rclone config from the
  Ansible vault alone was enough to list both remotes: 16 objects under `ha/`,
  19 under `pve/`, filenames decrypting correctly. The crypt password and OAuth
  token therefore survive without any cluster host.
- **Download an HA backup and confirm what is inside it.** Pulled the 963 MB
  automatic backup from `ha/` onto the laptop in 30 s: the outer tar lists
  `backup.json` plus one tar per add-on and `homeassistant.tar.gz`.

  **Correction to an earlier claim in this document: those inner archives are
  NOT plain tars.** They are SecureTar v3 — argon2id-derived key, XChaCha20-
  Poly1305 secretstream — encrypted with the backup password Home Assistant
  keeps in its own configuration (`create_backup.password`). Without that
  password the off-site HA backups are unreadable. It is now escrowed as
  `vault_ha_backup_password` in the Ansible vault, and validated
  cryptographically against a real archive: recomputing the header's validation
  key from the vault value returns a match, while a control string does not.
- **Restore an archive pulled back from Drive, and boot it.** `pve-restore-verify`
  does this monthly on pve01: fetch the smallest object from `pve/`, restore to
  throwaway VMID 998, strip NICs, boot, check userspace, destroy. Passed twice
  (17 s and 19 s, 14 running units).

**The vault password itself is escrowed off this machine.** It lives in 1Password
as item "Ansible Vault Password (homelab)" (Personal vault, id
`6x2qdqloldso6yx75oba3t74qq`), reachable as
`op read "op://Personal/6x2qdqloldso6yx75oba3t74qq/password"` from any device with
a 1Password session. `ansible/scripts/op-vault-pass.sh` is the Ansible
vault-password provider that reads it, and `docs/1password-hlxc-bridge.md`
documents the remote path through the op-broker. So a total loss of the cluster
and this laptop leaves: 1Password -> vault password -> Ansible vault -> rclone
crypt password + OAuth token -> the archives.

- **Restore the dependency root from the off-site copy.** authentik's 5.3 GB
  archive pulled from `pve/` and restored to throwaway VMID 997 on pve01 with
  its NICs stripped: restore 122 s, all four containers (server, worker,
  postgresql, redis) healthy, `authentik_core_user` count identical to
  production. PostgreSQL logged **"database system was not properly shut down;
  automatic recovery in progress"** — it recovered in under a second, which is
  exactly why `roles/authentik_pgdump` now writes a logical `pg_dump` inside the
  container at 02:45, before the 03:00 vzdump captures it (7-day retention,
  first dump 23 MB, `gzip -t` clean).

- **A VM restore, both ends of it.** mitm-generic's 1.6 GB VMA pulled from
  `pve/` and `qmrestore`d to throwaway VMID 996: **17 s** to restore, NICs
  stripped, guest kernel booted (AppArmor profiles at 3.4 s) and settled idle.
  Destroyed clean. (`qmrestore`, not `qm restore` — the latter does not exist.)
- **A Home Assistant restore, end to end, on a real spare instance — partial,
  then full.** HAOS 18.4 installed as a fresh VM on pve01 (VM 994,
  192.168.86.48), the 963 MB automatic backup uploaded to it and restored with
  the vaulted password.
  *Partial* (core config + `ssl` folder only): the *production* long-lived
  token authenticated against the spare — proving the auth store came back
  intact — 40 automations, 16 lights, but 1017 entities vs production's 1283,
  the 266 missing all integration-dependent because no add-ons were restored.
  *Full* (core config + `ssl` + all 12 add-ons in the archive): supervisor log
  ends `Partial-Restore 8c058769 done` after ~2 min, and the spare then reports
  **1279 entities vs production's 1283**, every key domain identical — 40
  automations, 16 lights, 636/637 sensors, 196 binary_sensors, 3 locks,
  67 switches, 5 climate, 13 media_players, 2 persons. All 12 add-ons came back
  and are registered: Portainer, Terminal & SSH, Advanced SSH & Web Terminal,
  Uptime Kuma, AppDaemon, Matter Server, Tailscale, Let's Encrypt, Get HACS,
  AdGuard Home, ESPHome Device Builder, Mosquitto broker. The 4 remaining
  entities are one scene, one sensor and two add-on `update.*` rows that only
  appear once those add-ons re-register.

  Two gotchas learned the hard way: the spare's core listened on **port 80**
  until the production config was restored, at which point it moved to **8123**
  like production — so "port closed" during a drill means "wrong port", not
  "broken restore". And `ha backups restore` refuses an archive whose
  `backup.json` says `type: partial` unless you name every item it holds
  (`--homeassistant --folders ssl --app <each slug>`); the archive here holds
  12 add-ons and only the `ssl` folder.

- **vm-01's own `daily/` VictoriaMetrics snapshot, replayed.** Pulled the newest
  object (`daily/20261027T141938Z/`, 1725 objects, 28.3 GiB) from Drive to
  `/nvme-pool/restore-verify/vm-daily` on pve01 and pointed a stock
  `victoria-metrics-prod` (v1.155.0) at the tree with
  `-storageDataPath=... -retentionPeriod=100y`. It came up in 0.135 s,
  `/health` 200, and served the archive's history:

  | query | replay | production |
  |---|---|---|
  | `ballooninfo_free_mem` @ 2026-10-26T12:00Z | 10 series, identical values | 10 series, same values |
  | `count({__name__!=""})` @ 2026-10-26/27 | 188k / 190k series | — |
  | month coverage | 2026_05 ... 2026_10 all present | — |

  Spot checks across the archive (`count_over_time(ballooninfo_free_mem[24h])`
  at mid-Sep, early-Oct, mid-Oct) all return data, and a point-for-point
  comparison against the live instance at the same timestamp matches exactly.
  Caveat worth knowing: the datastore was copied from a **running**
  `vmstorage`, so it is a point-in-time copy, not a quiesced snapshot — good
  enough to read history from, not a substitute for stopping the service first.
  Staging (`/nvme-pool/restore-verify/vm-daily`, 28 GiB) and the replay binary
  were deleted after the check; re-pulling from Drive is the restore path.

Nothing on the off-site path is left unproven: pull from Drive, decrypt,
restore a VM, restore an LXC with its database, restore Home Assistant in full,
and replay the metrics archive have all been exercised end to end.

## What exists off-site

| Remote path | Contents | Cadence | Retention |
|---|---|---|---|
| `vmbackup_crypt:pve/` | newest vzdump archive of each of the 17 production guests (`.tar.zst` for LXCs, `.vma.zst` for VMs) | weekly, Sat 05:00 | newest 4 per guest, pruned only after a successful copy |
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

Per VM (proven off-site — mitm-generic's 1.6 GB archive was pulled from Drive,
restored to throwaway VMID 996 and booted; note the command is `qmrestore`, there
is no `qm restore`):

```bash
qmrestore /nvme-pool/vzdump-backups/dump/vzdump-qemu-<vmid>-<stamp>.vma.zst <vmid> \
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
`vmbackup_crypt:ha/`; copy one back to `/backup` (or upload it through the API)
and restore it. Its config, add-ons and database are all inside that tarball.
Proven end to end on a throwaway HAOS VM: 1279 of production's 1283 entities and
all 12 add-ons came back, and the production long-lived token still
authenticated against the restored instance.

Two things that will waste an hour if you hit them fresh:

- **`ha backups restore` refuses an archive whose `backup.json` says
  `type: partial`** unless you name every item in it, e.g.
  `ha backups restore <slug> --password "$PW" --homeassistant --folders ssl --app core_letsencrypt --app a0d7b954_ssh …`.
  Name them all or it stops with "only a partial backup".
- **The web UI may not be on 8123.** A freshly onboarded HAOS VM answered on
  port 80; only after the production config was restored did it move to 8123.
  Check both before concluding the restore failed.

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

## The drill that closes the gap — automated

`pve-restore-verify.timer` on pve01 runs monthly (`*-*-01 04:30`
America/Chicago): it pulls the smallest object out of `vmbackup_crypt:pve/`,
restores it to throwaway VMID 998, strips the NICs, boots it, counts running
units and destroys it. It writes
`pve_restore_verify_last_success_timestamp_seconds`, and Grafana pages
(`restore_verify_stale`) if that metric goes missing for 45 days — so a backup
that has quietly stopped restoring cannot go unnoticed.

That covers the recurring proof. The one-off drills on 2026-10-27 covered the
paths the monthly job does not: a VM restore (`qmrestore`, VMID 996), an LXC
whose database has to come back (`authentik`, VMID 997), a full Home Assistant
restore, and replaying vm-01's VictoriaMetrics archive.
