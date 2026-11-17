#!/usr/bin/env python3
"""Unit tests for auto_merge.derive (no network, no guest)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_merge as am

fails = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  " + str(extra)) if extra else ""))
    if not cond:
        fails.append(label)


def ids(groups):
    return sorted(g["id"] for g in groups if not g.get("del") and am.is_auto(g))


# --- 1. the real pair rules ------------------------------------------------
folders = ["gemmajae", "gemmajaevip", "vip_emilyryder69", "emilyryder69",
           "thefortunecookie", "thefortunecookievip", "kyokocosplay",
           "kyokocosplaysfree", "chanxoxo-free", "chanxoxos",
           "mikan", "mikan_cosfree", "zeta", "zetafree", "gama"]
out = am.derive([], folders)
check("exact pair gemmajae", "auto:gemmajae" in ids(out), ids(out))
check("leading marker vip_emilyryder69", "auto:emilyryder69" in ids(out), ids(out))
check("near-miss kyokocosplaysfree", "auto:kyokocosplays" in ids(out), ids(out))
check("near-miss chanxoxo-free", "auto:chanxoxo" in ids(out), ids(out))
check("4-char prefix not paired", "auto:mikan" not in ids(out), ids(out))
check("plain zeta + zetafree paired", "auto:zeta" in ids(out), ids(out))
check("empty-folder gama ignored", all("gama" not in (g.get("folders") or []) for g in out))

# --- 2. a hand-made merge is never taken -----------------------------------
manual = [{"id": "gm1", "name": "chan", "folders": ["chanxoxo-free", "chanxoxos"], "ts": 1}]
out = am.derive(manual, folders)
check("manual claim blocks the derived pair", "auto:chanxoxo" not in ids(out), ids(out))
check("manual group preserved", any(g["id"] == "gm1" for g in out))

# --- 3. a dismissed pair stays dismissed -----------------------------------
tomb = [{"id": "auto:gemmajae", "name": "gemmajae", "folders": [], "ts": 5, "del": 1}]
out = am.derive(tomb, folders)
check("tombstoned pair not recreated", "auto:gemmajae" not in ids(out), ids(out))
check("tombstone kept", any(g["id"] == "auto:gemmajae" and g.get("del") for g in out))
# a live group on a dismissed id is retired
live_tomb = [{"id": "auto:gemmajae", "name": "g", "folders": ["gemmajae", "gemmajaevip"], "ts": 9},
             {"id": "auto:gemmajae", "name": "g", "folders": [], "ts": 10, "del": 1}]
out = am.derive(live_tomb, folders)
check("live+tombstone -> not live", "auto:gemmajae" not in ids(out))

# --- 4. new folders pair on the next run -----------------------------------
out = am.derive([], folders + ["newmodel", "newmodel_vip"])
check("new pair derived", "auto:newmodel" in ids(out), ids(out))

# --- 5. a member disappearing dissolves the pair ---------------------------
out = am.derive([], folders)
before = [g for g in out if g["id"] == "auto:gemmajae"][0]
out2 = am.derive(out, [f for f in folders if f != "gemmajaevip"])
check("dissolved when a member goes", "auto:gemmajae" not in ids(out2))
check("dissolution is a tombstone",
      any(g["id"] == "auto:gemmajae" and g.get("del") for g in out2))

# --- 6. idempotent: same input twice -> same output -------------------------
out3 = am.derive(out, folders)
check("idempotent (no new ts churn)",
      json.dumps(sorted(out, key=lambda g: g["id"]), sort_keys=True) ==
      json.dumps(sorted(out3, key=lambda g: g["id"]), sort_keys=True))

# --- 7. the real folder list from the guest -------------------------------
real = json.load(open("/tmp/real_folders.json")) if Path("/tmp/real_folders.json").exists() else None
if real:
    ledger = json.load(open("/tmp/real_merges.json")) if Path("/tmp/real_merges.json").exists() else {"groups": []}
    out = am.derive(ledger.get("groups", []), real)
    live = ids(out)
    manual_kept = [g["id"] for g in out if not am.is_auto(g) and not g.get("del")]
    print("real library -> live auto:", live, "| manual kept:", manual_kept)
    check("real library derives 4 pairs", len(live) == 4, live)
    check("real manual merges untouched", len(manual_kept) == 3, manual_kept)

# --- 8. identity pairs (source profiles) ----------------------------------
profiles = {
    "sexyoverdrive": {"source_id": "a1", "name": "ashmodel", "avatar": "av1",
                      "mentions": ["sexytestdrive"], "price": 0},
    "sexytestdrive": {"source_id": "b2", "name": "ashmodel", "avatar": "av2",
                      "mentions": [], "price": 8},
    "delta": {"source_id": "c3", "name": "delta", "avatar": "x", "mentions": [], "price": 5},
    "gama": {"source_id": "d4", "name": "gama", "avatar": "y", "mentions": [], "price": 5},
}
folders2 = ["sexyoverdrive", "sexytestdrive", "delta", "gama"]
out = am.derive([], folders2, profiles)
idpairs = [g for g in out if g["id"].startswith("auto:id:")]
check("bio cross-reference pairs the feeds", len(idpairs) == 1
      and idpairs[0]["folders"] == ["sexyoverdrive", "sexytestdrive"], idpairs)
check("same name but both paid -> not paired",
      not any(g["folders"] == ["delta", "gama"] for g in out))
st = am.derive([{"id": idpairs[0]["id"], "name": "x", "folders": [], "ts": 1, "del": 1}],
               folders2, profiles)
check("identity pair respects a tombstone",
      not any(g["id"] == idpairs[0]["id"] and not g.get("del") for g in st))
# a name rule wins over identity for the same folders
out2 = am.derive([], ["gemmajae", "gemmajaevip", "sexyoverdrive", "sexytestdrive"],
                 {"gemmajae": {"name": "g", "price": 0, "mentions": ["gemmajaevip"]},
                  "gemmajaevip": {"name": "g", "price": 0, "mentions": []},
                  "sexyoverdrive": profiles["sexyoverdrive"],
                  "sexytestdrive": profiles["sexytestdrive"]})
check("name pair and identity pair coexist",
      any(g["id"] == "auto:gemmajae" for g in out2)
      and sum(1 for g in out2 if g["id"].startswith("auto:id:")) == 1, [g["id"] for g in out2])
check("no profiles -> no identity groups",
      not any(g["id"].startswith("auto:id:") for g in am.derive([], folders2, {})))

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
