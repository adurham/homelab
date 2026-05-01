# Promtail + node_exporter → Grafana Alloy migration plan

Replace **two agents** on every host (Promtail for logs, node_exporter
for metrics) with **one** unified agent (Grafana Alloy). Reduces
binaries to maintain, systemd units, Renovate trackers, lint surface.

Background: Promtail was removed from Loki releases starting `v3.7.0`
(last bundled in `3.6.10`). Grafana is pushing Alloy as the unified
successor. Doing both Promtail and node_exporter together because Alloy
absorbs both via a single config; doing them separately would mean
running Alloy alongside node_exporter for an interim that has no value.

## Current vs after

**Current — two agents per host:**

```
systemd-journal ──► promtail ────► vm-01:3100 (Loki)
                    (loki/3.0.0)
/proc, /sys ──► node_exporter ────► :9100 ◄── vm-01 scrape pull
                (1.11.1)
```

**After — single agent per host:**

```
systemd-journal ┐
                ├── alloy ────► vm-01:3100 (Loki)
/proc, /sys ────┘    └─────► :9100 ◄── vm-01 scrape pull (unchanged)
```

VM's scrape config does NOT change — Alloy keeps serving on `:9100/metrics`
with the same shape `node_exporter` did (Alloy's built-in
`prometheus.exporter.unix` is a node_exporter fork).

## Component mapping

| Current | After |
|---|---|
| `roles/common_monitoring` (installs node_exporter) | repurpose → essentials only OR delete |
| `roles/promtail` | delete |
| (new) | `roles/alloy` |
| `roles/common_monitoring/templates/node_exporter.service.j2` | (gone — apt-installed alloy ships its own unit) |
| `roles/promtail/templates/promtail.yml.j2` | `roles/alloy/templates/config.alloy.j2` (river DSL) |
| `node_exporter_version`, `promtail_version` | `alloy_version` |

## River config sketch

```alloy
// Node-level metrics exposed on :9100 (replaces node_exporter).
prometheus.exporter.unix "host" {
    rootfs_path = "/"
    procfs_path = "/proc"
    sysfs_path  = "/sys"
}

prometheus.scrape "host_self" {
    targets         = prometheus.exporter.unix.host.targets
    scrape_interval = "15s"
    forward_to      = []        // VM still pulls; we don't push
}

// Journal scrape (replaces promtail's journal block).
loki.source.journal "system" {
    max_age    = "12h"
    labels     = {
        host = constants.hostname,
        job  = "systemd-journal",
    }
    forward_to    = [loki.write.vm01.receiver]
    relabel_rules = loki.relabel.journal_labels.rules
}

loki.relabel "journal_labels" {
    rule {
        source_labels = ["__journal__systemd_unit"]
        target_label  = "unit"
    }
    rule {
        source_labels = ["__journal_priority_keyword"]
        target_label  = "severity"
    }
    rule {
        source_labels = ["__journal__hostname"]
        target_label  = "nodename"
    }
}

loki.write "vm01" {
    endpoint {
        url = "http://172.16.0.42:3100/loki/api/v1/push"
    }
}
```

(Final form needs Alloy's HTTP server config so `:9100` actually
exposes the unix-exporter targets — the simplest pattern is using
`prometheus.scrape` with a self-target and not forwarding, but a
cleaner pattern uses Alloy's component-scrape architecture. Sort that
during the Phase-1 vm-01 dry-run.)

## Phased migration

### Phase 0: pre-work

1. Read the migration guides:
   - <https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/>
   - <https://grafana.com/docs/alloy/latest/set-up/migrate/from-prometheus/>
2. Verify Alloy package is in Grafana's apt repo (we already use it for
   Grafana itself — `roles/grafana/tasks/main.yml`'s "Add Grafana
   Repository").
3. Pick a Renovate-trackable version. `grafana/alloy` releases are
   tagged like `v1.X.Y`; latest stable as of writing is whatever's
   current. Pin it.

### Phase 1: parallel deploy on vm-01 only (safe)

1. Write `roles/alloy/`:
   - `defaults/main.yml` — `alloy_version`, `loki_url`,
     `alloy_listen_addr` (web UI; pick 12345 to dodge :9100 conflict
     on first-run).
   - `tasks/main.yml` — apt install (the Grafana repo is already
     configured); render config; deploy systemd unit override (apt
     ships one); start.
   - `templates/config.alloy.j2` — the river config above.
   - `handlers/main.yml` — Restart alloy.
2. Add `alloy` to play 3 (Configure VictoriaMetrics) in
   `deploy_monitoring.yml` — vm-01 only, alongside existing roles.
3. **Conflict on `:9100`** — node_exporter already serves it. For the
   first-run validation, run Alloy on `:9101`, query
   `http://vm-01:9101/metrics` to confirm output looks right. Don't
   touch VM's scrape config yet.
4. Verify on vm-01:
   - `systemctl is-active alloy` is `active`
   - `curl http://localhost:9101/metrics | head` shows node_*
     metrics
   - `curl http://localhost:3100/loki/api/v1/label/host/values`
     still shows `vm-01` (Alloy is shipping logs alongside Promtail —
     OK because Loki dedupes by content+timestamp on its receive path)

### Phase 2: vm-01 cutover

1. Move Alloy's metrics endpoint to `:9100`.
2. Stop+disable `node_exporter` and `promtail` on vm-01.
3. Start Alloy.
4. Verify VM still scrapes vm-01 successfully (`up{job="node_exporter",instance="vm-01"} == 1`).
5. Verify Loki still receives from vm-01 (`{host="vm-01"}` returns recent samples).
6. Watch for ~5 minutes. If anything's off, rollback (services + binaries are still on disk).

### Phase 3: fan out

For each remaining host (graf-01 + private_subnet — tanium-cluster
hosts excluded; their node_exporter/promtail status was always TBD):

1. Add `alloy` to play 2 + play 4 in `deploy_monitoring.yml`.
2. Stop+disable node_exporter and promtail; enable alloy.
3. Verify per-host: `up{instance="<host>"}` and `{host="<host>"}`
   both still return.

### Phase 4: cleanup

1. Remove `node_exporter` install tasks from `roles/common_monitoring`.
   The role becomes an empty no-op — delete it OR reduce to "ensure
   apt is fresh" if used by something else.
2. Delete `roles/promtail/`.
3. Remove `node_exporter_version` from `roles/common_monitoring/defaults/main.yml`.
4. Update Renovate config:
   - Remove manager for `node_exporter_version`.
   - Remove manager + packageRule for `promtail_version`.
   - Add manager for `alloy_version` tracking `grafana/alloy` releases.
5. Update `README.md`'s Observability section.
6. Update `docs/ipam.md` (no IP changes; just commentary about agent
   topology).

## Smoke tests

Run after each phase:

```bash
# Alloy active everywhere
ansible 'vm-01:graf-01:private_subnet' -m shell -a 'systemctl is-active alloy'

# :9100 still serves node-exporter-shaped metrics on every host
ansible 'vm-01:graf-01:private_subnet' -m shell -a 'curl -fs http://localhost:9100/metrics | grep ^node_load1 | head -1'

# All hosts still ship logs
ansible vm-01 -m shell -a 'curl -s http://localhost:3100/loki/api/v1/label/host/values'

# VM `up` query — count of healthy targets shouldn't drop
ansible vm-01 -m shell -a 'curl -s "http://localhost:8428/api/v1/query?query=up%7Bjob%3D%22node_exporter%22%7D" | python3 -c "import json,sys; d=json.load(sys.stdin); print(\"up=\", sum(1 for r in d[\"data\"][\"result\"] if r[\"value\"][1]==\"1\"))"'

# Synthesize an OOM after migration; verify log_oom_kill still fires
ansible pve03 -m shell -a 'pct exec 106 -- logger "Out of memory: Killed process 99999 (alloy-migration-test)"'
```

## Rollback (per host)

```bash
# On the affected host:
systemctl stop alloy
systemctl disable alloy

systemctl start node_exporter
systemctl enable node_exporter

systemctl start promtail
systemctl enable promtail
```

Configs and binaries stay on disk through Phase 3. Phase 4 is the
point of no return — and even then `git revert` brings back the role
files within minutes.

## Risks / sticking points

- **River label semantics differ from Promtail.** Our `log_*` alerts
  filter on `unit=`, `host=`, `unit!~"grafana-server.service|loki.service|promtail.service"`
  — verify these labels still resolve correctly post-migration. The
  `loki.relabel` block should produce identical labels, but there's a
  per-host risk where `__journal__systemd_unit` is empty (transient
  scope sessions) and Alloy emits a different default than Promtail
  did.
- **Position files don't carry over.** Alloy starts fresh on the journal
  cursor — a few minutes of overlap is possible (Loki dedupes by
  content+timestamp). Acceptable.
- **`prometheus.exporter.unix` collector defaults.** Different from
  `node_exporter`'s defaults in subtle ways (e.g., `systemd` collector
  enable). Audit the `set_collectors` list to match the metrics our
  alerts query (`node_filesystem_*`, `node_memory_*`, `node_load*`,
  `node_cpu_seconds_total`).
- **Alloy's apt package on Debian 12.** Need to confirm Grafana's apt
  repo serves it for `bookworm` — it does, but the repo URL might
  differ from the existing `packages.grafana.com/oss/deb` we use.
  Possibly need to add `apt.grafana.com`.
- **Removing `roles/common_monitoring`** — if other roles include it
  via `roles/<x>/meta/main.yml` `dependencies:`, deleting it breaks
  them. Sweep before deletion.

## Resource estimate

Alloy is heavier than node_exporter alone but lighter than
node_exporter + promtail combined:

- node_exporter alone: ~30-50 MB RSS
- promtail alone: ~50-100 MB RSS
- alloy (both): ~100-150 MB RSS

Net change: roughly equal or slightly lower per host. Not a concern.

## Effort estimate

- Phase 1 (vm-01 parallel): ~30 min
- Phase 2 (vm-01 cutover): ~15 min
- Phase 3 (fan out): ~15 min
- Phase 4 (cleanup): ~30 min

**Total ~90 min focused.** Should be one session, not split.

## Status as of 2026-05-01

- Loki: 3.7.1 (current)
- Promtail: 3.0.0 (last bundled with Loki)
- node_exporter: 1.11.1 (current)
- Alloy migration: planned, not started.
