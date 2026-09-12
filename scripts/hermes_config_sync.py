#!/usr/bin/env python3
"""Sync delegate_task/auxiliary model-routing decisions from the ansible
hermes_gateway role's vars/model_routing.yml into a local Hermes
~/.hermes/config.yaml.

WHY THIS EXISTS
----------------
The MacBook's local ~/.hermes/config.yaml and the hermes-gw-01 gateway's
ansible-rendered config.yaml are two independently-maintained copies of the
same delegate_task/auxiliary routing table. They drifted out of sync three
separate times (2026-09-04, -07, -08, -12) via manual copy-paste, including
a real bug (delegation.by_provider.anthropic silently pinning claude-sonnet-5
as PRIMARY on one copy after the other was already fixed).

ansible/roles/hermes_gateway/vars/model_routing.yml is now the single
written source of truth for "which model handles which delegate_task
persona / auxiliary task". The ansible role renders config.yaml.j2 from it
directly; this script is the other half -- it applies the SAME data to a
local, non-ansible-managed config.yaml.

WHAT THIS SYNCS (routing decisions only)
-----------------------------------------
  - delegation.model_by_role.<role>.{model,provider,fallback}
  - delegation.by_provider.<provider>.{model,provider}
  - auxiliary.anthropic.<task>.{model,provider,fallback}
  - auxiliary.ollama-cloud.<task>  (scalar model id, or the nested
    consult.timeout dict)

WHAT THIS DELIBERATELY DOES NOT TOUCH
---------------------------------------
  - model.default / model.provider (which provider is MAIN on this host)
  - agent.max_turns / timeouts / system_prompt_mode (host-specific tuning)
  - providers.ollama-cloud.* (the gateway hardcodes context_length overrides
    with discover_models: false; the local config has no providers.ollama-
    cloud block at all and gets correct context lengths via live
    auto-discovery instead -- that already works, don't disturb it)
  - Any reasoning_effort / timeout field on an auxiliary task that the
    ansible vars file does not itself set. Local has per-task
    reasoning_effort tuning the gateway config never carried; this script
    preserves those local-only fields rather than deleting them just
    because the source dict doesn't have the key. (auxiliary.anthropic.
    consult.timeout is the one field BOTH sides set, so an actual value
    change there DOES sync -- e.g. 180 -> 300.)

USAGE
-----
  python3 scripts/hermes_config_sync.py                 # dry run, shows diff
  python3 scripts/hermes_config_sync.py --apply          # writes the file
  python3 scripts/hermes_config_sync.py --check          # exit 1 if drifted, no output
  python3 scripts/hermes_config_sync.py --config PATH --vars-file PATH

Run from anywhere; --vars-file defaults to this repo's
ansible/roles/hermes_gateway/vars/model_routing.yml (resolved relative to
this script's own location, not cwd).
"""
import argparse
import difflib
import io
import shutil
import sys
from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VARS_FILE = REPO_ROOT / "ansible/roles/hermes_gateway/vars/model_routing.yml"
DEFAULT_CONFIG = Path.home() / ".hermes/config.yaml"


def make_yaml():
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # avoid re-wrapping long scalar strings
    y.indent(mapping=2, sequence=4, offset=2)  # matches hermes-agent's own dump style
    return y


def load_yaml(path):
    y = make_yaml()
    with open(path) as f:
        return y.load(f), y


def dump_yaml(data, y):
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def merge_task_entry(local_val, source_val):
    """Merge one routing leaf. Scalars: source wins outright. Dicts: shallow
    merge, source keys win, local-only keys (e.g. reasoning_effort) survive."""
    if isinstance(source_val, dict):
        if not isinstance(local_val, dict):
            return dict(source_val)
        merged = dict(local_val)
        for k, v in source_val.items():
            merged[k] = v
        return merged
    return source_val


def sync_subtree(config, path_parts, source_dict, changes, missing_locally, extra_locally):
    """path_parts: list of keys to walk/create in config down to the parent
    dict that directly holds the per-role/per-task entries."""
    cur = config
    for p in path_parts:
        if p not in cur or not isinstance(cur.get(p), dict):
            cur[p] = {}
        cur = cur[p]

    label = ".".join(path_parts)
    for key, source_val in source_dict.items():
        local_val = cur.get(key)
        if key not in cur:
            missing_locally.append(f"{label}.{key} (added)")
        merged = merge_task_entry(local_val, source_val)
        if merged != local_val:
            changes.append((f"{label}.{key}", local_val, merged))
        cur[key] = merged

    for key in cur:
        if key not in source_dict:
            extra_locally.append(f"{label}.{key}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Local Hermes config.yaml to sync into")
    ap.add_argument("--vars-file", type=Path, default=DEFAULT_VARS_FILE, help="ansible model_routing.yml source of truth")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry-run diff only)")
    ap.add_argument("--check", action="store_true", help="Exit 1 if drift exists, no output (for scripting/hooks)")
    args = ap.parse_args()

    if not args.vars_file.exists():
        print(f"vars file not found: {args.vars_file}", file=sys.stderr)
        return 2
    if not args.config.exists():
        print(f"config file not found: {args.config}", file=sys.stderr)
        return 2

    source, _ = load_yaml(args.vars_file)
    config, y = load_yaml(args.config)

    with open(args.config) as f:
        original_text = f.read()

    changes = []
    missing_locally = []
    extra_locally = []

    sync_subtree(config, ["delegation", "model_by_role"],
                 source["hermes_routing_model_by_role"], changes, missing_locally, extra_locally)
    sync_subtree(config, ["delegation", "by_provider"],
                 source["hermes_routing_delegation_by_provider"], changes, missing_locally, extra_locally)
    sync_subtree(config, ["auxiliary", "anthropic"],
                 source["hermes_routing_auxiliary_anthropic_tasks"], changes, missing_locally, extra_locally)
    sync_subtree(config, ["auxiliary", "ollama-cloud"],
                 source["hermes_routing_auxiliary_ollama_cloud_tasks"], changes, missing_locally, extra_locally)

    new_text = dump_yaml(config, y)

    if args.check:
        return 1 if new_text != original_text else 0

    if not changes:
        print("No drift detected -- local config already matches ansible's model_routing.yml.")
        return 0

    print(f"{len(changes)} routing value(s) differ from ansible/roles/hermes_gateway/vars/model_routing.yml:\n")
    for path, old, new in changes:
        print(f"  {path}")
        print(f"    local:  {old}")
        print(f"    source: {new}")
    if missing_locally:
        print(f"\nAdded (present in ansible, missing locally): {len(missing_locally)}")
        for m in missing_locally:
            print(f"  + {m}")
    if extra_locally:
        print(f"\nLocal-only entries NOT in ansible (left untouched, not removed):")
        for e in extra_locally:
            print(f"  ? {e}")

    print("\n--- unified diff (config.yaml) ---")
    diff = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(args.config),
        tofile=str(args.config) + " (after sync)",
    )
    sys.stdout.writelines(diff)

    if not args.apply:
        print("\nDry run only -- rerun with --apply to write these changes.")
        return 0

    backup = args.config.with_name(
        args.config.name + f".bak-routing-sync-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(args.config, backup)
    with open(args.config, "w") as f:
        f.write(new_text)
    print(f"\nWrote {args.config}\nBackup saved: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
