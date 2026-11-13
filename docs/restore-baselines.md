# Restore baselines

Captured values to compare against after a restore. A green "it opened"
is not a data-integrity proof — these numbers are the thing that makes it
one. Re-capture immediately before any backup you intend to rely on.

## Postgres (Patroni pair, `grafana_prod_utf8`)

Captured 2026-11-12 from the current leader (pg-02, 172.16.0.48):

```
LSN=0/6FB4ACD8  users=1  dashboards=14  datasources=2
```

Query used:

```sql
select 'LSN='||pg_current_wal_lsn()
     ||' users='||(select count(*) from "user")
     ||' dashboards='||(select count(*) from dashboard)
     ||' datasources='||(select count(*) from data_source);
```

Restore proof: replay a base backup + WAL into a **scratch plain postgres**
(not under Patroni, so it cannot join or get promoted), `pg_verifybackup`,
then compare these four numbers. A restore that reaches a different LSN is
not wrong — but the row counts must match the value captured at backup time.

## Garage bucket `loki`

Captured 2026-11-12:

```
Objects: 759170   Size: 1.5 GB (1.4 GiB)
```

Restore proof: a metadata-only restore proves nothing — Garage splits block
data from object metadata, and metadata is what makes objects visible. The
minimum bar is an S3 `list-objects` manifest with **ETag + size per object**,
matching this count, plus a ranged GET on a few objects to confirm real
bytes. A count alone detects gross loss only.

## Still missing

Neither baseline has an accompanying backup-time capture yet — they were
taken from the live system. Until a manifest is captured *alongside* a
backup, any restore proof can only establish "it opens and is at LSN X".
Do not let that read as "backups verified".

## Smoke restore performed 2026-11-12

Archive: `vzdump-lxc-149-2026_11_12-02_18_24.tar.zst` (dns-02, 217 MB
compressed / 708 MB uncompressed) on `vzdump-nvme`.

What was actually run, and what it proves:

1. `zstd -t <archive>` → passes. The archive decompresses end to end with
   no corruption. (Does **not** prove the guest boots.)
2. `tar -tf` lists the real filesystem, including
   `./var/cache/bind/db.chi.lab.amd-e.com` and `db.lab.amd-e.com`.
3. Extracting `./var/cache/bind/db.chi.lab.amd-e.com` yields a binary BIND
   journal containing this environment's actual records — `auth`,
   `authentik`, `dns-01`, `adblock-proxy-01` under `chi.lab.amd-e.com`.
   That is the content proof: not "a file exists" but "the right records
   are in it".
4. Extracting `./etc/bind/named.conf.options` returns a readable config.

**Scope of this proof:** it shows the backup is intact and contains correct,
environment-specific data. It does **not** show that `pct restore` produces
a booting guest with working networking and services — that needs a real
restore to a spare VMID, which has not been done. Do not let this document
be read as "restores verified".

Note: vzdump targets `vzdump-nvme` (local, `/nvme-pool/vzdump-backups`), **not**
the Garage cluster — so backup integrity does not depend on the Garage layout.

## Full `pct restore` drill performed 2026-11-13

Beyond the smoke test: an actual restore of a live guest to a spare VMID.

Archive: `vzdump-lxc-149-2026_11_13-02_08_07.tar.zst` (dns-02).

```
pct restore 999 <archive> --rootfs nvme-data:4     # no --start
```

Result:
- config regenerated with the **original** hostname `dns-02`, MAC
  `BC:24:11:82:FB:F1` and IP `172.16.0.14` — which is exactly why it must
  **not** be started: it would collide with the live guest.
- `rootfs: nvme-data:subvol-999-disk-1,size=4G`
- mounted rootfs = 347 MB, containing a real `/etc/bind` (4 `*.conf*`
  files plus `bind.keys`). Not an empty shell.
- destroyed afterwards with `pct destroy 999 --purge`.

**Operational note:** a long `pct restore` run through `pve-shell` (or any
console proxy that idles out) gets killed mid-extract, leaving
`lock: create` on the guest and no `rootfs:` line. Clean up with
`pct unlock <vmid>` then `pct destroy`, and re-run the restore detached:

```
setsid nohup sh -c "pct restore 999 <archive> --rootfs nvme-data:4 > /tmp/r999.log 2>&1" < /dev/null &
```

This proves the restore path works end to end (storage driver, rootfs
regeneration, config merge). It still does **not** prove the guest boots
with working services — that needs a start on an isolated network.
