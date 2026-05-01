# Promtail → Grafana Alloy migration plan

Promtail was removed from Loki releases starting at **v3.7.0** (last
bundled in `v3.6.10`). Grafana's go-forward log shipper is **Grafana
Alloy** — a unified observability collector that supersedes Promtail,
Grafana Agent, and various other shippers.

We currently run **Promtail 3.0.0** on every host, pushing to **Loki
3.7.1** on `vm-01`. Older Promtail talking to newer Loki is officially
supported, so the current state is functional and not urgent.

## Why migrate

- Promtail is end-of-life. Once a CVE lands and isn't backported, we're
  exposed.
- Renovate currently tracks Promtail against `grafana/loki` releases
  (since Promtail used to ship there). After v3.7.0 every Renovate PR
  for Promtail will 404 — we've disabled the tracker via packageRule
  to avoid the noise.
- Alloy's config DSL (`river`) gives us a path toward unifying log
  shipping with metrics scraping (Alloy can replace node_exporter
  too, eventually).

## Pre-work

1. Read the Promtail-to-Alloy migration guide:
   <https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/>
2. Read the Alloy install docs for Debian/Ubuntu:
   <https://grafana.com/docs/alloy/latest/set-up/install/linux/>
3. Sketch the equivalent of our current `promtail.yml.j2` in `river`
   syntax. Today's promtail config is small (single `journal` scrape,
   four labels, push to Loki) — should be a tight river config.

## Migration shape

Two reasonable approaches:

### Option A — replace `promtail` role with `alloy` role

1. Write a new `roles/alloy/` modeled on the existing `promtail/`:
   - `defaults/main.yml`: `alloy_version`, `loki_url` (same as
     promtail's), `alloy_port`.
   - `templates/alloy.river.j2`: river-syntax journal scrape that
     emits the same labels we use today (`host`, `job`, `unit`,
     `severity`, `nodename`).
   - `tasks/main.yml`: install Alloy from the Grafana apt repo OR
     binary download; render config; deploy systemd unit; start.
   - `handlers/main.yml`: Restart alloy.
2. In `deploy_monitoring.yml`, swap `promtail` for `alloy` in the
   three plays where it appears (Install Node Exporter, Configure
   VictoriaMetrics, Configure Grafana).
3. Stop and disable the existing `promtail.service` on every host.
4. Verify all 9 hosts still appear in Loki's `host` label values.
5. Re-enable Renovate tracking for Alloy (separate `customManagers`
   entry pointing at `grafana/alloy` releases).
6. Remove the disabled-tracking package rule for Promtail.
7. (Eventually) delete `roles/promtail/`.

### Option B — keep both during transition

Run Promtail and Alloy side-by-side for a week, validate Alloy is
shipping cleanly, then remove Promtail. Lower risk, but doubles log
volume to Loki temporarily and requires Promtail to keep working.

I'd default to **A** — Promtail still works, but the rip-and-replace is
simpler than a transition period.

## Sticking points to watch

- **Journal scrape labels**: river's `loki.source.journal` block has
  different label-discovery semantics than promtail's
  `journal.labels`. Need to map each one.
- **systemd-journal access**: Alloy needs the same root-or-journal-
  group access we gave Promtail. Same `User=root` in the systemd unit
  is fine, or grant `systemd-journal` group membership.
- **Loki push URL**: same shape as Promtail's
  (`http://vm-01:3100/loki/api/v1/push`). No change.
- **Position file**: Alloy stores its own positions; Promtail's
  `/var/lib/promtail/positions.yaml` becomes unused. Old logs already
  ingested won't be re-shipped (Loki dedupes by content + timestamp).

## Quick smoke test post-migration

```bash
# All hosts still labeled?
ansible vm-01 -m shell -a 'curl -s http://localhost:3100/loki/api/v1/label/host/values | python3 -m json.tool'

# Recent log lines flowing?
ansible vm-01 -m shell -a 'curl -sG http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode "query={job=\"systemd-journal\"}" --data-urlencode "limit=3"'

# loki_write_errors alert quiet?
ansible vm-01 -m shell -a 'curl -s "http://localhost:8428/api/v1/query?query=rate(loki_request_duration_seconds_count%7Broute%3D%22loki_api_v1_push%22%2Cstatus_code%3D~%225..%22%7D%5B5m%5D)"'
```

## Rollback

If Alloy doesn't work or ships fewer/different labels than expected:
re-enable promtail.service on every host, disable alloy.service. The
position files are independent so no data is lost.

## Status as of 2026-05-01

- Loki bumped to 3.7.1 (commit pending) — works correctly with
  Promtail 3.0.0 client.
- Promtail held at 3.0.0 (last version that was bundled).
- Renovate tracking for Promtail disabled via packageRule.
- Alloy migration: deferred; this doc is the playbook for when picked
  up.
