"""Validate PRIORITY_ESCALATE_OVERRIDES: Game Room escalates (donors -> 0%)
sooner than the flat PRIORITY_ESCALATE_OVER, in both the priority pass and
the fan-assist pass. Added 2026-08-31 per user request to prioritize Game
Room further -- it's been the warmest occupied room most cycles.

No pytest / appdaemon needed: same stub pattern as test_delivery_penalty.py.
"""
import sys
import types
from datetime import datetime, timedelta

# ---- stub appdaemon module BEFORE importing the controller -------------------
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")
class _Hass:
    def __init__(self, *a, **k): pass
hassapi.Hass = _Hass
pkg_ad = types.ModuleType("appdaemon")
pkg_pl = types.ModuleType("appdaemon.plugins")
pkg_hs = types.ModuleType("appdaemon.plugins.hass")
sys.modules["appdaemon"] = pkg_ad
sys.modules["appdaemon.plugins"] = pkg_pl
sys.modules["appdaemon.plugins.hass"] = pkg_hs
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

sys.path.insert(0, "/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps")
import smart_vent_controller as svc  # noqa: E402

# ---- fake HA backend ---------------------------------------------------------
class FakeHA(svc.SmartVentController):
    def __init__(self):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 8, 31, 15, 0, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        self.logs = []
    def datetime(self, aware=False):
        return self._clock
    def get_state(self, entity, attribute=None):
        if attribute:
            return self.attrs.get((entity, attribute))
        return self.states.get(entity)
    def set_state(self, entity, state=None, attributes=None):
        self.published[entity] = (state, attributes or {})
    def log(self, msg, *a, **k):
        self.logs.append(msg)

def fresh():
    ha = FakeHA()
    for _zn, zone in svc.ZONES.items():
        for _rn, s in zone["rooms"].items():
            ha.states[s["temp"]] = 72.0
            if s.get("occupancy"):
                ha.states[s["occupancy"]] = "off"
            for v in s.get("vents", []):
                ha.attrs[(v, "current_tilt_position")] = 100
    return ha

def find_key(ha, room):
    for zn, zone in svc.ZONES.items():
        if room in zone["rooms"]:
            return (zn, room)
    raise KeyError(room)

PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)

SP = 73.0  # cool setpoint, matches live thermostat as of 2026-08-31
GAME_ROOM = "Game Room"

# ---- Sanity: the override is actually registered for Game Room ---------------
check("Game Room has a PRIORITY_ESCALATE_OVERRIDES entry lower than the default",
      svc.PRIORITY_ESCALATE_OVERRIDES.get(("upstairs", GAME_ROOM), svc.PRIORITY_ESCALATE_OVER)
      < svc.PRIORITY_ESCALATE_OVER)

# ---- Test 1: priority pass escalates Game Room's donors at its override,
#      even though it's below the flat PRIORITY_ESCALATE_OVER threshold ------
ha = fresh()
k = find_key(ha, GAME_ROOM)
gr_over = svc.PRIORITY_ESCALATE_OVERRIDES[k]
assert gr_over < svc.PRIORITY_ESCALATE_OVER, "test assumes override is tighter than default"
tk = svc.ZONES[k[0]]["rooms"][GAME_ROOM]["temp"]
ha.states[svc.ZONES[k[0]]["rooms"][GAME_ROOM]["occupancy"]] = "on"
ha.states[tk] = SP + gr_over + 0.1   # just past ITS override, still well under the flat default
donor = find_key(ha, "Basement")
ha.states[svc.ZONES[donor[0]]["rooms"]["Basement"]["temp"]] = SP - 3.0  # clearly cooler donor
positions = {}
for zn, zone in svc.ZONES.items():
    for rn in zone["rooms"]:
        positions[(zn, rn)] = 100
out = ha._apply_priority_rooms(dict(positions), "cooling", SP, None)
check("T1 priority pass: Game Room escalates donors to 0% below the flat 3.0F threshold",
      out[donor] == svc.PRIORITY_DONOR_POS_ESCALATED)
print("    Basement donor position:", out[donor],
      "(Game Room off-by", round(SP + gr_over + 0.1 - SP, 2), "F, override", gr_over, "F, default", svc.PRIORITY_ESCALATE_OVER, "F)")

# ---- Test 2: a different room at the SAME off-by-setpoint margin does NOT
#      escalate yet (proves this is per-room, not a global change) -----------
ha2 = fresh()
# Control room must be a room that can still BE a beneficiary — i.e. NOT
# donor_only. Cat Room was used here originally but became donor_only on
# 2026-09-02 (cats are a real heat load but not a comfort requirement), which
# made it permanently beneficiary-ineligible and invalidated this test's
# premise. Guest Bedroom 2 is upstairs, has no escalate override, and is a
# normal human-occupied room, so it isolates the same variable.
CONTROL_ROOM = "Guest Bedroom 2"
k2 = find_key(ha2, CONTROL_ROOM)  # upstairs room without an escalate override
tk2 = svc.ZONES[k2[0]]["rooms"][CONTROL_ROOM]["temp"]
ha2.states[svc.ZONES[k2[0]]["rooms"][CONTROL_ROOM]["occupancy"]] = "on"
ha2.states[tk2] = SP + gr_over + 0.1   # same off-by-setpoint as T1
donor2 = find_key(ha2, "Basement")
ha2.states[svc.ZONES[donor2[0]]["rooms"]["Basement"]["temp"]] = SP - 3.0
positions2 = {}
for zn, zone in svc.ZONES.items():
    for rn in zone["rooms"]:
        positions2[(zn, rn)] = 100
out2 = ha2._apply_priority_rooms(dict(positions2), "cooling", SP, None)
check("T2 other rooms are unaffected: same off-by-setpoint stays at 50% (not escalated)",
      out2[donor2] == svc.PRIORITY_DONOR_POS)
print(f"    Basement donor position ({CONTROL_ROOM} beneficiary, no override):", out2[donor2])

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
