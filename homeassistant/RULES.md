# Home Assistant Development Rules

## Access

- REST API (primary): `http://homeassistant.local:8123`, authenticated with a
  long-lived token stored in `homeassistant/ha_config.env` (gitignored).
- SSH (secondary, for `ha` CLI and on-host file ops):
  `ssh -p 2222 root@homeassistant.local`.
- All deploys flow through `ansible/deploy_ha_automations.yml`. There is no
  legacy shell script; anything in older docs referring to
  `deploy_homeassistant.sh` or `setup_venv.sh` is stale.

## File Layout

- `configuration.yaml` — top-level HA config. Includes every other file in
  this directory.
- `automations.yaml` — UI-managed automations. HA owns this file; do not
  hand-edit it in the repo. It is currently a small placeholder.
- `automations/<system>.yaml` — repo-managed automations, one file per
  logical system. Wired in via the `homeassistant.packages.manual_automations`
  block in `configuration.yaml`, which loads the directory with
  `!include_dir_merge_list automations/`. Subdirectories under `automations/`
  (e.g. `automations/entertainment/`) only work because each is its own
  package — `!include_dir_merge_list` itself does NOT recurse.
- `scripts.yaml`, `scenes.yaml` — UI-managed; HA owns these.
- `scripts/`, `scenes/`, `themes/` — placeholder dirs (each with a
  `.gitkeep`) so the `!include_dir_*` directives in `configuration.yaml`
  resolve without warning, even before we have any content.
- `templates.yaml`, `sensors.yaml`, `input_*.yaml` — included directly from
  `configuration.yaml`. Helper entities (input_boolean, input_number,
  counter, timer, input_text) must be defined directly in
  `configuration.yaml` or its included files; HA does not accept a
  `<domain> custom:` style include for these.
- `apps/apps.yaml` — placeholder for future AppDaemon apps. Currently empty.
  The deploy playbook still copies it for consistency.
- `secrets.yaml` (not in repo) — lives on the HA host only at
  `/config/secrets.yaml`. Holds `sony_tv_psk` and
  `grafana_alert_webhook_id`. Template: `secrets.yaml.example`.
- `ha_config.env` (not in repo) — `HA_URL` + `HA_TOKEN` for the helper
  Python scripts. Template: `ha_config.env.example`.

### Naming

- snake_case for file and directory names.
- Stable, descriptive IDs in automations and scripts.

## Deployment

The deploy playbook is `ansible/deploy_ha_automations.yml`. Run from the
repo root.

```bash
# Fast path: reload automations via REST API, no HA restart.
ansible-playbook ansible/deploy_ha_automations.yml

# Slow path: required whenever configuration.yaml, templates.yaml,
# sensors.yaml, or any input_*.yaml changes — those cannot be hot-reloaded.
ansible-playbook ansible/deploy_ha_automations.yml -e ha_restart=true
```

What the playbook does, in order:

1. `yamllint homeassistant/` on the control node — aborts on lint errors.
2. `ha core backup --name pre-deploy-<timestamp>` on the HA host.
3. scp the automation tree and the top-level config files into `/config/`.
4. `ha core check` on the HA host — aborts (and prints stderr) on failure.
5. Either reload automations via REST (`reload_ha_automations.py`) or
   `ha core restart`, depending on `ha_restart`.

## Validation

Local:

```bash
yamllint homeassistant/
ansible-lint ansible/deploy_ha_automations.yml   # optional but recommended
```

Remote:

```bash
ssh -p 2222 root@homeassistant.local "ha core check"
```

## Orphan Entities

Deleted automations leave behind `state: unavailable` entries in HA's
entity registry. Inspect and prune them with:

```bash
# Read-only — lists every automation.* with current state.
python3 homeassistant/prune_orphan_entities.py --list-all

# Read-only — shows only orphans (state: unavailable). Default mode.
python3 homeassistant/prune_orphan_entities.py

# Destructive — actually removes orphan registry entries. Requires both flags.
python3 homeassistant/prune_orphan_entities.py --apply --i-know-what-im-doing
```

## Security

- Never commit `ha_config.env`, `secrets.yaml`, or HA backup archives.
  All three are gitignored.
- The deploy playbook always takes a `ha core backup` before pushing — if
  validation fails on the host, restore with
  `ha core backup restore <slug>`.
- The `homeassistant` Hermes toolset blocks dangerous service domains
  (`shell_command`, `command_line`, `python_script`, `rest_command`,
  `hassio`, `pyscript`); call concrete device domains instead.

## Error Handling

- Local YAML errors fail the playbook before anything touches the host.
- Remote `ha core check` failure surfaces stderr via an explicit `fail:`
  task — read it; do not blindly re-run.
- If automations reload but a single automation is broken, HA marks it
  `unavailable` rather than crashing. Use the pruner above to clean those
  up after fixing the source file.

## Adding New Systems

1. Drop a new file under `automations/<system>.yaml`.
2. Run `yamllint homeassistant/` locally.
3. Deploy with `ansible-playbook ansible/deploy_ha_automations.yml` (no
   restart needed unless you also touched `configuration.yaml`).
4. Verify the entity appears in Developer Tools → States; if it shows
   `unavailable`, check `ha core log`.
