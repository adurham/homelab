"""Validate the downstairs/basement occupied-cooling ladder (added 2026-09-02).

THE BUG this replaces: _auto_calculate added a flat +1.0F "occupied urgency
bonus" to a room's `need` (temp - target_cool) BEFORE comparing it against
OCC_DEADBAND_DOWNSTAIRS (1.5F). That silently halved the user's actual
intended margin -- a room only 0.5F raw over setpoint already scored 1.5F
and opened to 100%. Confirmed live 2026-09-02: Living Room at 72.86F against
a 72F setpoint (raw +0.86F) was opening to 100%, and the user explicitly
said downstairs vents should stay FULLY CLOSED until an occupied room is
genuinely >1.0F over setpoint.

THE FIX: a three-tier ladder measured against RAW distance-over-setpoint
(captured before any heat-rise/occ_bonus adjustment), applied ONLY to
occupied downstairs/basement rooms during cooling:
    raw <= 1.0F            -> 0%   (fully closed, no trickle/hysteresis)
    1.0F < raw <= 2.0F      -> 50%  (half flow)
    raw > 2.0F              -> 100% (full flow)
Upstairs and all heating scoring are UNCHANGED (fall through to the
original occ_deadband/`need` logic untouched).

No pytest / appdaemon needed: same stub pattern as the other tests in tests/.
"""
import sys
import types
from datetime import datetime

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
        self._clock = datetime(2026, 9, 2, 15, 0, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        # saturation state machine (2026-09-02)
        self._saturation_streak = {}
        self._saturated_rooms = set()
        self._saturation_recover = {}
        self._last_zone_positions = {}
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

def find_key(ha, room):
    for zn, zone in svc.ZONES.items():
        if room in zone["rooms"]:
            return (zn, room)
    raise KeyError(room)

def fresh():
    """Every room at setpoint (72F), unoccupied, so only the room we set up
    for a given check actually drives interesting logic."""
    ha = FakeHA()
    for _zn, zone in svc.ZONES.items():
        for _rn, s in zone["rooms"].items():
            ha.states[s["temp"]] = 72.0
            if s.get("occupancy"):
                ha.states[s["occupancy"]] = "off"
    return ha

def set_downstairs_occupied_room(ha, room, temp):
    """Occupy a downstairs room and set its raw temp (setpoint fixed at 72F
    by every check below, so raw off-setpoint == temp - 72.0)."""
    key = find_key(ha, room)
    zone_name, room_name = key
    assert zone_name == "downstairs", f"{room} is not downstairs"
    sensors = svc.ZONES[zone_name]["rooms"][room_name]
    ha.states[sensors["temp"]] = temp
    if sensors.get("occupancy"):
        ha.states[sensors["occupancy"]] = "on"
    return key

PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)

SP = 72.0  # cool setpoint used by every scenario below

# =============================================================================
# 1. AT/UNDER the 1.0F open threshold -> fully CLOSED (0%), no trickle.
#    This is the exact live scenario that motivated the fix: Living Room at
#    72.86F (raw +0.86F) must NOT open at all.
# =============================================================================
ha = fresh()
lr = set_downstairs_occupied_room(ha, "Living Room", 72.86)
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T1 raw +0.86F (under 1.0F threshold) -> 0% (fully closed)",
      out[lr] == 0)

# Exactly at the boundary (raw == 1.0F, not strictly greater) -> still closed.
ha = fresh()
lr = set_downstairs_occupied_room(ha, "Living Room", 73.0)
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T2 raw exactly +1.0F (boundary, not strictly over) -> 0% (fully closed)",
      out[lr] == 0)

# =============================================================================
# 2. BETWEEN the two thresholds -> 50% (half flow).
# =============================================================================
ha = fresh()
lr = set_downstairs_occupied_room(ha, "Living Room", 73.5)  # raw +1.5F
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T3 raw +1.5F (between 1.0F and 2.0F) -> 50%", out[lr] == 50)

# Exactly at the upper boundary (raw == 2.0F, not strictly greater) -> still 50%.
ha = fresh()
lr = set_downstairs_occupied_room(ha, "Living Room", 74.0)  # raw +2.0F
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T4 raw exactly +2.0F (boundary, not strictly over) -> 50% (not yet 100%)",
      out[lr] == 50)

# =============================================================================
# 3. PAST the 2.0F full threshold -> 100%.
# =============================================================================
ha = fresh()
lr = set_downstairs_occupied_room(ha, "Living Room", 74.5)  # raw +2.5F
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T5 raw +2.5F (over 2.0F) -> 100% (fully open)", out[lr] == 100)

# =============================================================================
# 4. Ladder applies to Kitchen too (any occupied downstairs room, not just
#    Living Room) -- Kitchen has no occupancy sensor (always occupied).
# =============================================================================
ha = fresh()
kk = find_key(ha, "Kitchen")
ha.states[svc.ZONES["downstairs"]["rooms"]["Kitchen"]["temp"]] = 72.7  # raw +0.7F
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T6 Kitchen raw +0.7F (always-occupied, no sensor) -> 0% (fully closed)",
      out[kk] == 0)

# =============================================================================
# 5. Basement gets the same ladder (zone_name in ("downstairs", "basement")).
# =============================================================================
ha = fresh()
bs = find_key(ha, "Basement")
ha.states[svc.ZONES["basement"]["rooms"]["Basement"]["occupancy"]] = "on"
ha.states[svc.ZONES["basement"]["rooms"]["Basement"]["temp"]] = 72.5  # raw +0.5F
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T7 Basement occupied raw +0.5F -> 0% (fully closed, ladder applies)",
      out[bs] == 0)

# =============================================================================
# 6. UPSTAIRS IS UNCHANGED: an occupied upstairs room at the same raw
#    deviation still uses the ORIGINAL occ_deadband/need logic (OCC_DEADBAND_
#    UPSTAIRS = 1.0F, no ladder, no raw_off_setpoint substitution). Confirms
#    the fix is scoped to downstairs/basement only, per its stated intent.
# =============================================================================
ha = fresh()
gb1 = find_key(ha, "Guest Bedroom 1")
ha.states[svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]["occupancy"]] = "on"
# raw +0.86F, same as T1's Living Room scenario, but upstairs -- with the
# UPSTAIRS_HEAT_RISE_BONUS added, `need` clears OCC_DEADBAND_UPSTAIRS (1.0F)
# and this room legitimately opens under the UNCHANGED upstairs logic.
ha.states[svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]["temp"]] = 72.86
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T8 upstairs occupied room at the SAME raw deviation as T1's Living "
      "Room is NOT forced closed (ladder does not apply upstairs)",
      out[gb1] != 0)

# =============================================================================
# 7. HEATING IS UNCHANGED: the ladder only gates `is_cooling` branches.
# =============================================================================
ha = fresh()
lr = find_key(ha, "Living Room")
ha.states[svc.ZONES["downstairs"]["rooms"]["Living Room"]["occupancy"]] = "on"
ha.states[svc.ZONES["downstairs"]["rooms"]["Living Room"]["temp"]] = 63.0  # raw 1.0F under heat setpoint
out = ha._auto_calculate("heat_cool", "heating", None, 64.0)
# Heating keeps the flat DEADBAND-based logic (need = target_heat - temp = 1.0,
# occ_bonus adds 1.0 -> need=2.0 -> > occ_deadband(DEADBAND=1.0) -> 100%).
# The exact value isn't the point here -- the point is it did NOT go through
# the cooling-only ladder branch (which would have produced 50%, not 100%,
# for a 1.0F raw deviation).
check("T9 heating is unaffected by the cooling-only ladder "
      "(flat need-based logic still applies)",
      out[lr] == 100)

# =============================================================================
# 10. PRIORITY-PASS CONSISTENCY (bug fix, same day as the ladder itself):
#     _apply_priority_rooms has its OWN independent "is this room struggling
#     enough to be pinned to 100% and draft donor CFM" threshold, previously
#     disconnected from the ladder's thresholds -- so a room the ladder
#     correctly scored 50% got immediately yanked back to 100% here because
#     it cleared this pass's own (lower) margin. Reproduces the exact live
#     bug (2026-09-02): Kitchen at 73.2F (raw +1.2F, correctly 50% per the
#     ladder) while Game Room roasts at 79.3F -- Kitchen must NOT become a
#     100% beneficiary (that would fight the whole point of redirecting air
#     upstairs), and specifically must remain ELIGIBLE to donate to Game
#     Room, since a comfortable-ish downstairs room feeding a roasting
#     upstairs room is exactly the desired behavior.
# =============================================================================
ha = fresh()
gr = find_key(ha, "Game Room")
ha.states[svc.ZONES["upstairs"]["rooms"]["Game Room"]["occupancy"]] = "on"
ha.states[svc.ZONES["upstairs"]["rooms"]["Game Room"]["temp"]] = 79.3
# Kitchen has no occupancy sensor -- set its temp directly rather than via
# the downstairs-occupied helper, which asserts an occupancy sensor exists.
kk = find_key(ha, "Kitchen")
ha.states[svc.ZONES["downstairs"]["rooms"]["Kitchen"]["temp"]] = 73.2  # raw +1.2F
auto_out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T10 pre-priority: ladder correctly scores Kitchen 50% (raw +1.2F)",
      auto_out[kk] == 50)
priority_out = ha._apply_priority_rooms(dict(auto_out), "cooling", SP, None, "Auto")
check("T10 post-priority: Kitchen is NOT yanked to 100% as a beneficiary "
      "(stays at the ladder's 50%, or is thrown lower as a DONOR to Game "
      "Room -- either is correct, 100% is the only wrong outcome)",
      priority_out[kk] != 100)
check("T10 Game Room (genuinely roasting, off+7.3F) IS a full 100% beneficiary",
      priority_out[gr] == 100)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
