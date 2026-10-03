# roles/victoriametrics

VictoriaMetrics (Prometheus-compatible TSDB) on vm-01. Receives metrics
pushed by Alloy (every managed host) and pulled from its own
`blackbox_exporter` scrape jobs (Tanium postgres/console, cert expiry,
iframe checks) defined in `prometheus.yml.j2`.

Note: the Tanium appliances (`tanium_cluster`) run **no** monitoring
agent — the old `:9100` node_exporter scrape job was retired 2026-08-09
(TanOS default-deny iptables never exposed the port, and these vendor
appliances run no custom software). Tanium host-down detection now comes
from the agentless `blackbox_tanium_reachable` TCP/22 probe.

## What it does

- Downloads the upstream binary (`victoria-metrics-prod`) from the
  GitHub releases pinned by `victoriametrics_version`.
- Renders the systemd unit + scrape config (`prometheus.yml.j2`).
- Sets `-retentionPeriod=2y` (two years of metric history; coupled with
  blackbox/loki disk pressure alerts).
- Configures blackbox probe targets for: HTTPS cert-expiry on the
  public-facing endpoints (`blackbox_https_targets`), Tanium postgres
  (5432/5433), Tanium server consoles (:443).

## Key variables (`defaults/main.yml`)

- `victoriametrics_version` — Renovate-tracked against
  `VictoriaMetrics/VictoriaMetrics` releases.
- `blackbox_https_targets` — list of HTTPS URLs to probe for cert/probe
  alerts.
- `exo_scrape_targets` — exo inference cluster `/metrics` endpoints.
- `windows_exporter_scrape_targets` — in-guest Windows VMs (:9182).
  Empty; populate once a VM is booted, has a static IP, and the role ran.
- `node_exporter_scrape_targets` — in-guest node_exporter (:9100) for
  QEMU VM guests. **Empty**, and correctly so today (see below).

## QEMU VM disk coverage (disk_full / "Disk usage high")

The `disk_full` rule alerts on `node_filesystem_*` under
`job="node_exporter"`. LXC guests were already covered; QEMU VMs were
not. Two supported ways a QEMU Linux VM gets covered, both requiring no
rule change (the rule's generic OR-branch matches any
`node_filesystem_*{instance!~"tc-.*"}` — it filters on the metric name +
instance, **not** on `job`):

1. **Alloy push (preferred for general-purpose Linux VMs).** Grafana
   Alloy (`roles/alloy`) emits node_exporter-shape metrics under
   `job="node_exporter"` via remote-write, so simply running Alloy on the
   VM covers it — no scrape entry here.
2. **Pull scrape.** Populate `node_exporter_scrape_targets` once the VM
   is booted, has a static IP, and node_exporter actually listens on
   :9100 (the repo has **no** node_exporter install role).

### Current status (verified live 2026-10-03): 0/6 running QEMU VMs covered

Every QEMU VM is **blocked** from in-guest monitoring, so the empty
target lists are correct, not an oversight:

- **ts-01/ts-02, tms-01/tms-02, tzs-01/tzs-02 (200–205, all running)** —
  TanOS (Tanium) **vendor appliances**. Standing direction: no custom
  software (node_exporter was removed 2026-08-09; see
  `cleanup_tanium_node_exporter.yml`). SSH works for 4/6 (ts/tms) but a
  node_exporter install still violates the appliance policy and would
  need an iptables hole for :9100. **Policy-blocked.**
- **usda-* (210–214, 222–225), win-* (250–258), templates (9000–9002) —
  powered off**, `onboot=0` by design, no static IPs. Nothing to deploy
  to. **Blocked until powered on + given IPs.**
- The Windows path (`windows_exporter_scrape_targets`) is likewise still
  0/8 Windows VMs (all powered off).

**Future path for the appliances (not built):** QGA's whitelist permits
`get-fsinfo` (verified live on ts-01: `qm guest cmd 200 get-fsinfo`
returns real mountpoints/used/total) even though `guest-exec` is denied.
That would give host-side, agentless disk accounting for the appliances
without installing anything in-guest, but it needs a custom collector —
out of scope here. Recorded so the next attempt doesn't re-discover it.

## Where it's invoked

`deploy_monitoring.yml`'s play `Configure VictoriaMetrics` (play 8), along
with `pve_exporter`, `blackbox_exporter`, `loki`, `alloy` and `vm_backup`.

For a **scrape-config-only** re-render (without the broad
`deploy_monitoring.yml`, whose first play recreates the monitoring CTs),
use the narrow `ansible/deploy_victoriametrics_scrape.yml` (`hosts:
victoriametrics`, i.e. vm-01 only).
