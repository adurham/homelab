# roles/ups_autoshutdown

Orderly guest shutdown + auto-recovery for the lab-corner UPS
(CyberPower GX1500U on pve01). Watches the UPS via NUT (`roles/nut_ups`),
and when the corner is genuinely running out of battery, stops every guest
gracefully — then restarts exactly what it stopped once mains is stable.

## Why this exists

The lab corner is fed by the UPS so it rides out the recurring deep sags
(`docs/ipam.md` INCIDENT CLASS B). But the GX1500U only holds the whole
corner for a few minutes at load: if an outage outlasts the battery, guests
die hard — the failure class that has already corrupted data on this
cluster. This role converts "battery exhausted → hard kill" into "battery
low → orderly stop → auto-restart when mains returns".

## Architecture

One daemon, on the UPS-owning node (pve01). It talks to the whole cluster
through `pvesh` / `ha-manager`, which are cluster-wide from any node — so
one instance covers pve01/02/03 guests alike.

```
nut-server (upsd, localhost)  →  upsc  →  ups_autoshutdown daemon
                                             │  pvesh /cluster/resources (enumerate)
                                             │  pvesh .../status/shutdown (non-HA guests)
                                             │  ha-manager crm-command stop (HA guests)
                                             ▼
                                   state.json  →  textfile metrics → Alloy → VictoriaMetrics → Grafana
```

HA-managed guests (12 CTs incl. authentik, tailscale-gw, grafana, HA-adjacent
services) are stopped through `ha-manager crm-command stop <sid> <timeout>`,
which both shuts the guest down gracefully AND writes `state=stopped` into
the HA config so the CRM does not immediately restart/relocate it. Non-HA
guests use the plain status API. Recovery reverses exactly that (and for HA
guests flips `state` back to `started`).

## Trigger

All of these must hold, evaluated every `poll_seconds` (default 5s):

1. UPS reports on-battery (`OB` in `ups.status`)
2. continuously for `ob_sustain_seconds` (default 60s) — a two-second blip
   that immediately recovers never fires
3. AND either `battery.charge <= stop_charge_percent` (default 20%)
   OR `battery.runtime <= stop_runtime_seconds` (default 300s)

The second condition catches the case where charge percentage lies (an
aging battery can read 40% and still have 2 minutes left), which is exactly
the failure mode this UPS already showed on install day.

## Stop sequence

1. **Phase 1**: guests whose name matches `phase1_name_regex` (default
   `^tc-` — the disposable Tanium test fleet) get graceful stops first.
2. **Phase 2**: everything else (HA and non-HA alike).
3. Each guest gets `graceful_timeout_seconds` (90s) to shut down; if it is
   still running after +`hard_stop_grace_seconds` (30s), it is force-stopped.
4. Whole sequence is capped at `sequence_deadline_seconds` (480s); at that
   point everything still pending is force-stopped. Rationale: the battery
   is the scarce resource — a half-stopped cluster dying at minute 12 is
   worse than one extra hard stop at minute 8.
5. **Abort window**: if mains returns and stays back for
   `abort_online_seconds` (30s) while the sequence is running, no further
   phases are issued and nothing gets force-stopped. In-flight stops finish;
   the normal recovery path restarts them.

## Recovery

Once in `stopped`, the daemon waits for mains to be **stable** for
`recovery_ol_seconds` (300s) — and if a recovery already happened within
`recovery_recent_window_seconds` (30 min), it demands an extra
`recovery_recent_extra_seconds` (300s) of stability. That second rule
handles a stuttering outage (mains flickers back, dies again) without
flapping the whole lab. It then starts exactly the guests recorded in
`state.json`. Start requests for guests that are still booting are
re-throttled to once per 30s.

It also never recovers while the UPS is unreadable or on battery again.

## What it explicitly does NOT do

- **Never shuts down a node.** Guests only. The three nodes stay up on
  battery, so the cluster (and this daemon) keeps running; if the battery
  exhausts, AC loss cuts them — the path all three already auto-recover
  from via BIOS AC-recovery settings (verified 2026-10-01: all three came
  back unattended after the rewire's power cut; pve02/03 are `AcPwrRcvry=On`,
  pve01 is `Last` — pve01 needs its BIOS flipped to `On` for that guarantee
  to hold for a *graceful* power loss).
- **Never touches excluded VMIDs** (`exclude_vmids` default empty).
- **Never acts while `/var/lib/ups-autoshutdown/disabled` exists** — one
  file to make it a no-op without stopping the daemon.

## The three safety layers

1. `dry_run: true` (default on deploy) — evaluates and logs
   `DRY RUN: would stop N guests (...)`, writes `ups_autoshutdown_would_trigger 1`,
   and stops nothing. **Flip to false only after watching it through a real
   on-battery event** (or a staged test) and confirming the guest list and
   timing are what you expect.
2. `disabled` flag file — instantaneous operator kill switch:
   `ups-autoshutdown disable` / `enable`.
3. The built-in selftest runs on every ansible deploy and fails the play if
   the state machine regressed (`ups-autoshutdown selftest`, 8 scenarios,
   in-memory backend, never touches the cluster).

## Operator commands

```
ups-autoshutdown status                  # live UPS + state + evaluation
ups-autoshutdown stop --only 302,105     # controlled stop of specific guests (tracked)
ups-autoshutdown recover                 # restart tracked guests now
ups-autoshutdown disable | enable        # kill switch
ups-autoshutdown selftest                # scenario tests
```

`state.json` (in `/var/lib/ups-autoshutdown/`) holds the state machine,
the tracked guest list, and a rolling history of transitions — it is the
first thing to read when something looks wrong.

## Metrics

Written every cycle to `/var/lib/node_exporter/textfile_collector/ups_autoshutdown.prom`
(rides the same Alloy textfile collector as `roles/nut_ups`):

- `ups_autoshutdown_state_info{state,mode}` — current state machine state
  (`monitoring` / `stopping` / `stopped` / `recovering` / `disabled`)
- `ups_autoshutdown_lab_stopped` — 1 while the lab is auto-stopped
- `ups_autoshutdown_triggered` — 1 from trigger through recovery complete
- `ups_autoshutdown_would_trigger` — 1 when trigger conditions are met but
  dry-run is on (this is the dry-run observability signal; alert on it)
- `ups_autoshutdown_guests_running` — running guest count
- `ups_autoshutdown_ob_seconds` — continuous seconds on battery

## Where it's invoked

- `deploy_ups_autoshutdown.yml` — targeted (role + config + selftest),
  run against pve01.
- `deploy_monitoring.yml` — a `hosts: proxmox_nodes` play gated on
  `nut_ups_enabled`, placed just after the NUT play.

## Deployment state

**ARMED 2026-10-01** (`ups_autoshutdown_dry_run: false` set per-host in
`inventory/proxmox.yml`, NOT in role defaults — so a fresh host still ships
in dry-run and a plain redeploy can't silently flip this). Arming followed a
staged live test that exercised both stop paths and the recovery path on
real guests:

- `ups-autoshutdown stop --only 302,105` → `tc-ubuntu24` (plain LXC) and
  `ntp-01` (HA-managed CT) both stopped gracefully via their correct paths;
  state machine reached `stopped`; `state.json` tracked both.
- `ups-autoshutdown recover` → both restarted; `ntp-01` was relocated to
  pve03 by the HA rebalance (expected — `ha-manager set --state started`
  lets the CRM place it) and chrony came back healthy/synced.

Disarm: `ups-autoshutdown disable` on pve01 (instant, until reboot/enable),
or set the inventory var back to `true` and re-run the deploy.

## First-event checklist (when the alert fires for real)

1. `ups-autoshutdown status` on pve01 — confirm state + why it tripped.
2. If still dry-run: read the journal (`journalctl -u ups-autoshutdown -n 100`),
   confirm the "would stop" list matches expectations, then decide.
3. After mains returns: confirm the automatic recovery ran, and that guest
   count is back to baseline (`/cluster/resources`).
4. Record the timings (battery %, runtime, stop duration) in `docs/ipam.md`.
