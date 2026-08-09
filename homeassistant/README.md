# Home Assistant Configuration

This directory holds the Home Assistant config that lives in version control.
The source of truth is this repo; the live HA host is updated via the Ansible
playbook at `ansible/deploy_ha_automations.yml`.

## Quick Start

1. Bootstrap your local API credentials (gitignored):

   ```bash
   cp homeassistant/ha_config.env.example homeassistant/ha_config.env
   # Edit homeassistant/ha_config.env and set HA_URL + HA_TOKEN.
   # Get a long-lived token at http://homeassistant.local:8123/profile.
   ```

2. First-time install (writes files AND restarts HA so configuration.yaml
   takes effect):

   ```bash
   cd ~/repos/homelab
   ansible-playbook ansible/deploy_ha_automations.yml -e ha_restart=true
   ```

3. Day-to-day automation edits (no restart, hot-reload via REST API):

   ```bash
   ansible-playbook ansible/deploy_ha_automations.yml
   ```

Use `-e ha_restart=true` whenever `configuration.yaml`, `templates.yaml`,
`sensors.yaml`, or any `input_*.yaml` changes — those cannot be hot-reloaded.

## Directory Structure

```
homeassistant/
├── configuration.yaml         # Top-level HA config; loads everything below.
├── automations.yaml           # UI-managed automations (HA owns this file).
├── automations/               # Repo-managed automations (one file per system).
│   └── entertainment/         # Sub-package for media-room automations.
├── apps/apps.yaml             # Unused placeholder (/config/apps/ — see below).
├── appdaemon/                 # AppDaemon apps (real vent-control logic lives here).
│   ├── appdaemon.yaml
│   ├── apps/                  # smart_vent_controller.py + its apps.yaml.
│   └── tests/                 # Offline unit tests (no AppDaemon/pytest needed).
├── docs/                      # Reference docs / device inventories.
├── input_datetime.yaml        # input_datetime helpers.
├── input_number.yaml          # input_number helpers.
├── scripts.yaml               # UI-managed scripts (HA owns this file).
├── sensors.yaml               # Custom sensors.
├── templates.yaml             # Template entities.
├── secrets.yaml.example       # Template for secrets.yaml (HA-host only).
├── ha_config.env.example      # Template for ha_config.env (gitignored).
├── reload_ha_automations.py   # Helper used by the deploy playbook.
└── prune_orphan_entities.py   # Lists / removes stale automation entities.
```

`automations/` is wired into HA via `!include_dir_merge_list` inside the
`homeassistant.packages.manual_automations` block in `configuration.yaml`.
That packaging is what lets repo-managed automations coexist with the
UI-managed `automations.yaml` HA edits in place.

## Live Systems

Brief tour of what is actually running. See the matching files under
`automations/` for the gory details.

- Safety — `automations/emergency_safety.yaml`,
  `automations/circulation_safety.yaml`. Smoke / CO emergency response and
  HVAC circulation watchdog.
- Infrastructure alerting — `automations/adguard_watchdog.yaml`,
  `automations/frigate_watchdog.yaml`, `automations/disk_space_watchdog.yaml`,
  `automations/smart_vent_watchdog.yaml`, `automations/grafana_alert_webhook.yaml`.
  Liveness monitors (AdGuard, Frigate NVR, HA host disk space, Smart Vent
  Controller's AppDaemon heartbeat) and the Grafana → iPhone push bridge.
  `smart_vent_watchdog.yaml` self-heals via `hassio.addon_restart` on
  heartbeat staleness >6min, rate-limited to 1 restart/15min, escalates
  to a critical push if the restart doesn't clear it — see the 2026-08-08
  incident notes in its header comment.
- Lights — `cat_room_main_lights_{on,off}.yaml`,
  `front_porch_sconces_{on,off}.yaml`,
  `stairs_main_lights_{on,off}.yaml`,
  `garage_lights_door_motion_control.yaml`. Schedule- and motion-driven
  lighting for the recurring rooms.
- Climate / exhaust — `basement_exhaust_fan.yaml`. CO2-driven baseline and
  burst exhaust for the basement office.
- Smart vent control — `appdaemon/apps/smart_vent_controller.py` (AppDaemon
  app, not a YAML automation; config in `appdaemon/apps/apps.yaml`). Zones
  Flair vent airflow per-room by temperature, occupancy, and floor-level
  heat-rise physics; escalates airflow to struggling rooms by throttling
  satisfied donor rooms; enforces a coil-safety floor (dynamic backpressure
  from `sensor.ac_suction_line_temp`) so redirection never risks evaporator
  freeze. Deploys via the same `ansible/deploy_ha_automations.yml` playbook
  (AppDaemon hot-reloads the app on file change — no HA restart). Offline
  unit tests in `appdaemon/tests/`. All HA service calls (vent tilt, fan
  mode) are fire-and-forget (`callback=`), not blocking waits — this app
  runs on a single pinned AppDaemon worker thread, and a blocking call that
  never returns (2026-08-08 incident: a websocket response got orphaned)
  freezes the WHOLE app, including the periodic control loop, for as long
  as the wedge lasts. `automations/smart_vent_watchdog.yaml` +
  `sensor.smart_vent_controller_heartbeat` + a Grafana alert rule
  (`roles/grafana` → `smart_vent_controller_frozen`) all exist specifically
  to detect and self-heal this failure mode.
- Hot water — `hot_water_recovery.yaml`, `smart_circulation.yaml`. Recovery
  manager and (currently disabled) smart recirculation pump control.
- Laundry — `laundry_monitor.yaml`. Notifies when the washer cycle ends.
- Entertainment — `automations/entertainment/ps5_hue_sync.yaml`. Drives
  Hue sync box behavior off PS5 power state.

If something in the live HA registry shows `state: unavailable`, it is a
stale entity left behind from a deleted automation. Use
`python3 homeassistant/prune_orphan_entities.py --list-all` to inspect, and
the same script with `--apply --i-know-what-im-doing` to remove.

## Secrets

`secrets.yaml` lives only on the Home Assistant host (`/config/secrets.yaml`)
and is never copied by the deploy playbook — bootstrap it manually from
`secrets.yaml.example`. It currently holds:

- `sony_tv_psk` — pairing key for the Sony Bravia integration.
- `grafana_alert_webhook_id` — shared secret in the Grafana → HA webhook URL.

`ha_config.env` is the local credentials file the helper Python scripts
read (HA_URL, HA_TOKEN). Also gitignored. Bootstrap from
`ha_config.env.example`.

## Troubleshooting

```bash
# Validate the live HA config.
ssh -p 2222 root@homeassistant.local "ha core check"

# Tail the HA log.
ssh -p 2222 root@homeassistant.local "ha core log"

# Restore from a HA-CLI backup (the deploy playbook takes one before each push).
ssh -p 2222 root@homeassistant.local "ha core backup restore <slug>"
```

The deploy playbook runs `yamllint homeassistant/` locally before any scp,
takes a `ha core backup` on the host, copies files, runs `ha core check`,
then either reloads automations via REST or restarts core depending on
`ha_restart`.
