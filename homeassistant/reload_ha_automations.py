#!/usr/bin/env python3
"""Reload Home Assistant automations via the REST API.

Reads HA_URL and HA_TOKEN from homeassistant/ha_config.env and POSTs to
/api/services/automation/reload. Exits 0 on success, 1 on failure.

Used by ansible/deploy_ha_automations.yml after pushing automation files.
"""
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


def main() -> int:
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
        print("error: HA_URL and HA_TOKEN must be set in ha_config.env", file=sys.stderr)
        return 1

    endpoint = f"{url.rstrip('/')}/api/services/automation/reload"
    req = urllib.request.Request(
        endpoint,
        data=b"",
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            if resp.status != 200:
                body = resp.read().decode("utf-8", "replace")
                print(f"error: HA returned {resp.status}: {body}", file=sys.stderr)
                return 1
    except urllib.error.URLError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Automations reloaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
