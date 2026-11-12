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
