#!/usr/bin/env python3
"""List or remove orphaned automation entities from Home Assistant.

An "orphan" is an automation.* entity that exists in HA's registry but
whose source automation has been deleted from the repo — these show up
as state: "unavailable" in /api/states and clutter the UI.

Default behaviour is read-only DRY RUN: print the orphan list and exit.
Destructive removal requires BOTH --apply AND --i-know-what-im-doing.

Reads HA_URL and HA_TOKEN from homeassistant/ha_config.env (same loader
as reload_ha_automations.py). Uses only stdlib.

Removal strategy
================
HA's entity registry is mutated through the WebSocket API
(`config/entity_registry/remove`), not the REST API. Python's stdlib has
no built-in WebSocket client, and the brief forbids adding pip deps.

So `--apply` prints the exact `ha` CLI commands the operator can run via
ssh to remove each orphan from the registry on the HA host:

    ssh -p 2222 root@homeassistant.local "ha service call \\
        homeassistant.remove_entity entity_id=<orphan>"

If the `homeassistant.remove_entity` service is not available on your HA
version, fall back to deleting entries directly from
`/config/.storage/core.entity_registry` while HA is stopped — but that is
manual surgery and out of scope for this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def load_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def fetch_states(url: str, token: str) -> list[dict]:
    endpoint = f"{url.rstrip('/')}/api/states"
    req = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def filter_automations(states: list[dict]) -> list[dict]:
    return [s for s in states if s.get("entity_id", "").startswith("automation.")]


def filter_orphans(automations: list[dict]) -> list[dict]:
    return [a for a in automations if a.get("state") == "unavailable"]


def print_entity_table(entities: list[dict], title: str) -> None:
    if not entities:
        print(f"{title}: (none)")
        return
    print(f"{title}: {len(entities)} entit{'y' if len(entities) == 1 else 'ies'}")
    width = max(len(e.get("entity_id", "")) for e in entities)
    for i, e in enumerate(entities, 1):
        entity_id = e.get("entity_id", "")
        state = e.get("state", "")
        name = e.get("attributes", {}).get("friendly_name", "")
        print(f"  {i:>3}. {entity_id:<{width}}  [{state:<11}]  {name}")


def emit_removal_commands(orphans: list[dict]) -> None:
    print()
    print("To remove these orphan registry entries, run ON THE HA HOST:")
    print()
    for o in orphans:
        eid = o["entity_id"]
        print(
            f'    ssh -p 2222 root@homeassistant.local '
            f'"ha service call homeassistant.remove_entity entity_id={eid}"'
        )
    print()
    print(
        "If homeassistant.remove_entity is not exposed on your HA version, "
        "stop HA and edit /config/.storage/core.entity_registry manually."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or prune orphaned HA automation entities.",
    )
    parser.add_argument(
        "--list-all",
        action="store_true",
        help="List EVERY automation.* entity with state (read-only).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Print removal commands for orphan entities (still does not "
        "execute them; requires --i-know-what-im-doing).",
    )
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Second confirmation flag required alongside --apply.",
    )
    args = parser.parse_args()

    if args.apply and not args.i_know_what_im_doing:
        print(
            "Refusing to emit removal commands without "
            "--apply AND --i-know-what-im-doing.",
            file=sys.stderr,
        )
        return 2
    if args.i_know_what_im_doing and not args.apply:
        print(
            "--i-know-what-im-doing was passed without --apply; nothing to do.",
            file=sys.stderr,
        )
        return 2

    here = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(here, "ha_config.env")
    if not os.path.exists(config_path):
        print(
            f"error: {config_path} not found; copy ha_config.env.example",
            file=sys.stderr,
        )
        return 1

    env = load_env(config_path)
    url = env.get("HA_URL")
    token = env.get("HA_TOKEN")
    if not url or not token:
        print(
            "error: HA_URL and HA_TOKEN must be set in ha_config.env",
            file=sys.stderr,
        )
        return 1

    try:
        states = fetch_states(url, token)
    except urllib.error.URLError as exc:
        print(f"error fetching /api/states: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error decoding /api/states response: {exc}", file=sys.stderr)
        return 1

    automations = filter_automations(states)
    orphans = filter_orphans(automations)

    if args.list_all:
        print_entity_table(automations, "All automations")
        print()

    print_entity_table(orphans, "Orphan automations (state: unavailable)")

    if args.apply:
        if not orphans:
            print("\nNothing to remove.")
            return 0
        emit_removal_commands(orphans)

    return 0


if __name__ == "__main__":
    sys.exit(main())
