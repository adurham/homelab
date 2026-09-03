"""Validate donor_only room semantics, and specifically that Cat Room and
Guest Bathroom became donor_only on 2026-09-02.

Background (live incident, 2026-09-02 ~21:35): Game Room sat +11.2F over
setpoint with the controller logging "no donor rooms" available, while the
priority pass simultaneously logged:

    Priority Guest Bathroom (75.0F, off+3.0) [cool,ESCALATED] struggling
    upstairs/Cat Room: 74.8F empty need=+4.8 -> 100% (hot override)

Neither room has a human in it whose comfort matters:
  - Cat Room houses cats. They are a real, continuous sensible heat load, so
    the room genuinely reads warm and the base scoring reads that as demand --
    but there's no comfort requirement, so it must never win air away from a
    room people actually occupy.
  - Guest Bathroom is transient-use space (same reasoning as Hallway/Laundry).
    It already had max_vent_pct=50, but that only CAPS how far it opens; it
    does not stop it competing as a beneficiary in the priority pass.

donor_only semantics being locked in here:
  1. the room can never be a BENEFICIARY (never pins itself to 100% and
     never drafts donor CFM away from other rooms)
  2. the room CAN still be a DONOR (throttled to feed a hotter real room)
  3. its own vent still follows normal temp logic, including closing to 0%
     when satisfied -- max_vent_pct is a ceiling, not a floor

No pytest / appdaemon needed: same stub pattern as the other suites here.
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
        self._clock = datetime(2026, 9, 2, 21, 35, 0)
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

def find_key(ha, room_name):
    for zn, zone in svc.ZONES.items():
        if room_name in zone["rooms"]:
            return (zn, room_name)
    raise KeyError(room_name)

PASS = []
def check(label, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + label)

SP = 72.0

# =============================================================================
# 1. Config assertions -- the flag is actually set
# =============================================================================
for room in ("Cat Room", "Guest Bathroom"):
    zn, rn = find_key(fresh(), room)
    check(f"T1 {room} is marked donor_only in ZONES",
          svc.ZONES[zn]["rooms"][rn].get("donor_only") is True)

# Guest Bathroom must KEEP its 50% cap -- donor_only is additive, not a
# replacement for the no-return-duct stratification cap.
zn, rn = find_key(fresh(), "Guest Bathroom")
check("T2 Guest Bathroom still has max_vent_pct=50 (cap preserved)",
      svc.ZONES[zn]["rooms"][rn].get("max_vent_pct") == 50)

# Rooms that must NOT be donor_only -- real bedrooms/living space where a
# human's comfort is the whole point. Guards against a careless broad edit.
for room in ("Game Room", "Guest Bedroom 1", "Guest Bedroom 2", "Living Room"):
    zn, rn = find_key(fresh(), room)
    check(f"T3 {room} is NOT donor_only (real occupied space)",
          svc.ZONES[zn]["rooms"][rn].get("donor_only") is not True)

# =============================================================================
# 2. Behavior: neither room becomes a BENEFICIARY even when hot + "occupied"
#    Reproduces the live 2026-09-02 numbers.
# =============================================================================
for room, room_temp in (("Cat Room", 74.8), ("Guest Bathroom", 75.0)):
    ha = fresh()
    key = find_key(ha, room)
    ha.states[svc.ZONES[key[0]]["rooms"][room]["temp"]] = room_temp
    if svc.ZONES[key[0]]["rooms"][room].get("occupancy"):
        # even with the occupancy sensor reading ON (a cat tripping it, or a
        # transient bathroom visit), it must not become a beneficiary
        ha.states[svc.ZONES[key[0]]["rooms"][room]["occupancy"]] = "on"

    # A genuinely cooler room that WOULD be a valid donor if asked.
    donor = find_key(ha, "Basement")
    ha.states[svc.ZONES[donor[0]]["rooms"]["Basement"]["temp"]] = SP - 3.0

    positions = {}
    for zn, zone in svc.ZONES.items():
        for rn in zone["rooms"]:
            positions[(zn, rn)] = 100
    out = ha._apply_priority_rooms(dict(positions), "cooling", SP, None)

    check(f"T4 {room} at {room_temp}F does NOT draft the cooler Basement "
          f"as a donor (stays 100%, never became a beneficiary)",
          out[donor] == 100)

# =============================================================================
# 3. Behavior: both rooms CAN still be donors to a genuinely hot real room.
#    Game Room at 80.2F (the live value) must be able to take their air.
#
#    NOTE on fixture design: donors are sorted unoccupied-first then
#    COOLEST-first, and each beneficiary now gets a FAIR-SHARE budget of
#    PRIORITY_MAX_DONORS // n_beneficiaries (the 2026-09-02 donor-exhaustion
#    fix), so the worst room can no longer drain the pool. Donor eligibility
#    is judged against the BENEFICIARY's temp (must be >=
#    PRIORITY_DONOR_COOLER_BY cooler than 80.2F), NOT against the setpoint.
#    To isolate "are these two ELIGIBLE as donors at all" -- rather than
#    accidentally testing budget arithmetic -- make Game Room the ONLY
#    beneficiary (so it gets the full budget) and park the filler rooms at
#    76.0F: still eligible themselves, but WARMER than Cat Room (74.8) and
#    Guest Bathroom (75.0), so those two sort first and land inside the budget.
#    Filler rooms are left UNoccupied so they don't become beneficiaries and
#    fragment the budget.
# =============================================================================
ha = fresh()
KEEP = {"Game Room", "Cat Room", "Guest Bathroom"}
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn not in KEEP:
            ha.states[s["temp"]] = 76.0
            if s.get("occupancy"):
                ha.states[s["occupancy"]] = "off"
gr = find_key(ha, "Game Room")
ha.states[svc.ZONES[gr[0]]["rooms"]["Game Room"]["occupancy"]] = "on"
ha.states[svc.ZONES[gr[0]]["rooms"]["Game Room"]["temp"]] = 80.2
for room, room_temp in (("Cat Room", 74.8), ("Guest Bathroom", 75.0)):
    key = find_key(ha, room)
    ha.states[svc.ZONES[key[0]]["rooms"][room]["temp"]] = room_temp

positions = {}
for zn, zone in svc.ZONES.items():
    for rn in zone["rooms"]:
        positions[(zn, rn)] = 100
out = ha._apply_priority_rooms(dict(positions), "cooling", SP, None)

check("T5 Game Room (80.2F, occupied) IS pinned 100% as beneficiary",
      out[gr] == 100)
for room in ("Cat Room", "Guest Bathroom"):
    key = find_key(ha, room)
    check(f"T6 {room} IS still eligible as a DONOR to Game Room "
          f"(throttled below 100%)",
          out[key] < 100)

# =============================================================================
# 4. max_vent_pct is a CEILING, not a FLOOR -- Guest Bathroom must still be
#    able to close fully to 0% when it is satisfied. (User asked directly:
#    "guest bathroom capped at 50% but does that mean it stays open at 50%
#    all the time? cause it could be 0% right now")
# =============================================================================
ha = fresh()
gb = find_key(ha, "Guest Bathroom")
ha.states[svc.ZONES[gb[0]]["rooms"]["Guest Bathroom"]["temp"]] = SP - 2.0  # satisfied
out = ha._auto_calculate("heat_cool", "cooling", SP, 64.0)
check("T7 Guest Bathroom satisfied (2F BELOW setpoint) scores 0%, "
      "proving max_vent_pct=50 is a ceiling and not a floor",
      out[gb] == 0)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
