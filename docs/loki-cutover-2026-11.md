# Loki cutover: single vm-01 Loki -> HA ring behind the VIP (2026-11-15)

Status: **cut over.** Grafana's `loki` datasource reads the HA ring; the fleet ships to both
Lokis; the old Loki on vm-01 stays as a rollback path and as `loki-legacy` for history.

## What it was

- Old: one Loki on vm-01 (`172.16.0.42:3100`), filesystem storage, no redundancy.
- New (built 2026-11-12/13): loki-01/02/03 (CT 154/155/156, `.75/.76/.77`, one per PVE node),
  replication factor 3, chunks and index in Garage S3 (three nodes), reached through the load
  balancer VIP `172.16.0.30:3100`. Both have the same limits (4 MB/s ingest, retention enabled).
- The repo already pointed shippers at the VIP (commits `ed0cbac`, `08bcc363`), but nothing had been
  deployed: for three days every Alloy still pushed to vm-01 and Grafana still read vm-01, while the
  ring held logs from one test host. Deploying the repo as it stood would have sent every host's
  logs to a Loki Grafana never queried and silenced every log-based alert without an error.

## Order used (so there was never a gap)

1. `roles/alloy`: `loki_urls` list; the template renders one `endpoint` per entry and Alloy fans out
   to all of them, each with its own queue. `deploy_alloy.yml` rolls only that role, 5 hosts at a time.
2. `inventory/group_vars/all.yml`: `loki_urls` = [VIP, vm-01] (dual-write).
3. Pilot on lb-01 and tc-ubuntu22, then the 23 other log-shipping hosts, then vm-01 and graf-01
   (they are excluded from `deploy_monitoring.yml`'s agent play, so the first pass missed them).
4. **Proof before flipping:** over the same 4-minute window every host had *identical* line counts in
   both Lokis (ratio 1.00 for all 16 active hosts, nothing missing). The metrics-only-style hosts
   (media-ingest-01/02) showed only their allowlisted units (`cron`, `ssh`), so the privacy
   allowlist held after the template's filter order changed.
5. Grafana: `roles/grafana/templates/datasource.yml.j2` now points uid `loki` at
   `grafana_loki_url` (default the VIP) and adds uid `loki-legacy` for vm-01. Applied to graf-02,
   then graf-01, with a datasource reload (no restart). All 116 alert rules evaluated healthy
   afterwards; the only errors were evaluator rebuilds in the same second as the reload.
6. Four HA twins that had never run Alloy (graf-02, mail-02, ntp-02, vm-clus-03) were installed;
   they now ship logs and metrics.

Side effect worth knowing: rolling the role also moved each host's *metrics* remote-write from
`vm-01:8428` to the VIP `:8428` (the same intent as commit `08bcc363`, never deployed beyond pve01).
Metrics were verified fresh through the VIP afterwards.

## Not done on purpose

- **LAN-side hosts** (lan-dns-01/02, 192.168.86.x) cannot reach the private-subnet VIP, so they have
  no Alloy. They need a LAN-reachable endpoint (an LB vhost) before they can ship logs.
- **Unreachable by SSH** during this work (rebuilt, new host keys): garage-01/02/03, vm-clus-01/02,
  bwt-dhcp, pet-detector-01, tc-debian11, tc-rhel8, tc-rhel9. Their Alloy state is unknown.
- **History:** logs from before the cutover exist only in the old Loki (`loki-legacy` datasource).
  Nothing was migrated; Loki has no clean import.

## Rollback

Set `grafana_loki_url: http://172.16.0.42:3100` (group_vars), re-render
`roles/grafana/templates/datasource.yml.j2` on graf-01/02 and reload datasources
(`POST /api/admin/provisioning/datasources/reload`). Both Lokis hold the full stream while dual-write
is on, so no data is lost either way.

## Retiring the old Loki

After a week of clean operation: remove the vm-01 line from `loki_urls` in `group_vars/all.yml`
(the role default is then the VIP only), run `deploy_alloy.yml`, confirm the old Loki's ingest rate
drops to zero, then stop its `loki.service`. Keep `loki-legacy` until its data is not wanted.

## Follow-ups found after the flip (same evening)

- **Nothing scraped the new ring.** The `loki` scrape job pointed at `127.0.0.1:3100`, which is
  right on vm-01 and wrong on graf-02's own vmagent (it scraped its own localhost and wrote a
  contradictory `up` for vm-01). Now real addresses for vm-01 and loki-01/02/03, on both
  vmagents and in `roles/victoriametrics/templates/prometheus.yml.j2`, so "Loki rejecting
  writes" covers the ring. (Both vmagents read the same path but their copies have drifted;
  the Patroni and Loki edits were applied to each live file, not by re-rendering the template.)
- Three transient push 500s (`context canceled`, microseconds) on vm-01's Loki during the
  rollout are Alloy hosts reconnecting while they were restarted; harmless.
- `loki.write` fans out to both endpoints from one receiver. If one endpoint stalls while the
  other is healthy, check this Alloy version for back-pressure before the vm-01 line is removed:
  remove it while vm-01's Loki is still up, never after stopping it.
