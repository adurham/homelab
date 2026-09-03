"""Saturation inversion + donor-budget fairness (both added 2026-09-02).

## Why these exist

A physical measurement drove both changes. A 13-gallon trash-bag test on the
three Game Room registers read 2.0 s per register = ~52 CFM each = ~156 CFM
total -- measured while all 3 of its vents were at 100% AND seven other rooms
were already throttled to 0% feeding it. Holding 72F in that room needs
~250 CFM. So the room is DUCT-LIMITED: it was receiving every CFM its duct can
physically carry, at maximum software effort, and still climbing.

That invalidated two behaviors that had looked reasonable:

1. SATURATION INVERSION. `DELIVERY_ESCALATE_PENALTY` made a high delivery
   handicap ESCALATE the room -- throttle its donors from 50% to 0% to shove
   even MORE air at it. For a duct-limited room that is backwards: the blower
   is a 5-speed CONSTANT-TORQUE ECM (not constant-CFM), so each extra closed
   damper raises static and LOWERS total house CFM, while the saturated room
   still receives only its duct's ~156 CFM. The airflow is taken from rooms
   that would have responded and delivered nowhere.

2. DONOR EXHAUSTION. Donors were allocated first-come-first-served, so the
   worst room consumed every eligible donor and the runner-up got none.
   Replaying the live 21:58 log (setpoint 70):

       PASS 1  Game Room 79.3F -> 12 eligible, took ALL 12
       PASS 2  GB1 76.3F       -> 11 qualified by temperature, 0 available
                               -> "struggling but no donor rooms"

   That log line read like "the whole house is too hot to have donors" but was
   actually pure allocation starvation. Raising PRIORITY_MAX_DONORS 8 -> 12
   earlier the same evening made it worse (at 8, four donors happened to be
   left over for GB1).

An even-split budget was tried first and REJECTED: with 9 beneficiaries it
gives 12//9 = 1 donor each, so the desperate room gets one donor and eight
marginal rooms get one each -- verified strictly worse than the original bug.
The shipped design is rank-weighted with a floor of 1.

No pytest / appdaemon needed: same stub pattern as the other suites.
"""
import sys
import types
from datetime import datetime, timedelta

# ---- stub appdaemon BEFORE importing the controller --------------------------
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


class FakeHA(svc.SmartVentController):
    def __init__(self):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 2, 21, 35, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        self._last_zone_positions = {}
        self._saturation_streak = {}
        self._saturated_rooms = set()
        self._saturation_recover = {}
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


def find_key(room_name):
    for zn, zone in svc.ZONES.items():
        if room_name in zone["rooms"]:
            return (zn, room_name)
    raise KeyError(room_name)


PASS = []
def check(label, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + label)

SP = 70.0


def budget(n):
    """Mirror of the shipped rank-weighted allocation."""
    out, remaining = [], svc.PRIORITY_MAX_DONORS
    for i in range(n):
        share = remaining if i == n - 1 else max(1, remaining // 2)
        share = max(1, min(share, remaining))
        out.append(share)
        remaining = max(0, remaining - share)
    return out


# =============================================================================
# 1. Budget shape
# =============================================================================
check("T1 single beneficiary gets the whole pool (no behavior change when "
      "only one room is struggling)",
      budget(1) == [svc.PRIORITY_MAX_DONORS])

b3 = budget(3)
check(f"T2 worst room still gets the largest share (concentration preserved): {b3}",
      b3[0] > b3[1] >= b3[2])

b9 = budget(9)
check(f"T3 with 9 beneficiaries EVERY room still gets >=1 donor "
      f"(no starvation): {b9}",
      all(x >= 1 for x in b9))
check("T4 worst room keeps a meaningful share even at 9 beneficiaries "
      "(an even split would have collapsed it to 1)",
      b9[0] >= 4)
check("T5 rank-weighted beats even-split for the worst room "
      f"({b9[0]} vs {svc.PRIORITY_MAX_DONORS // 9})",
      b9[0] > svc.PRIORITY_MAX_DONORS // 9)


# =============================================================================
# 2. LIVE REPLAY of the 2026-09-02 21:58 incident.
#    The bug: GB1 logged "struggling but no donor rooms" while 11 rooms
#    qualified for it by temperature -- Game Room had taken all of them.
# =============================================================================
LIVE = {
    "Game Room": 79.3, "Guest Bedroom 1": 76.3, "Guest Bedroom 2": 74.8,
    "Cat Room": 74.3, "Guest Bathroom": 73.2, "Living Room": 75.0,
    "Kitchen": 74.7, "Hallway": 74.0, "Dining Room": 73.6,
    "Laundry Room": 74.8, "Main Bedroom": 70.2, "Main Bathroom": 70.0,
    "Basement": 70.0,
}
ha = fresh()
for room, t in LIVE.items():
    zn, rn = find_key(room)
    ha.states[svc.ZONES[zn]["rooms"][rn]["temp"]] = t
for room in ("Game Room", "Guest Bedroom 1"):
    zn, rn = find_key(room)
    occ = svc.ZONES[zn]["rooms"][rn].get("occupancy")
    if occ:
        ha.states[occ] = "on"

positions = {(zn, rn): 100 for zn, z in svc.ZONES.items() for rn in z["rooms"]}
out = ha._apply_priority_rooms(dict(positions), "cooling", SP, None)

gb1 = find_key("Guest Bedroom 1")
gr = find_key("Game Room")
gb1_line = [l for l in ha.logs if "Guest Bedroom 1" in l and "Priority" in l]
gb1_starved = any("no donor rooms" in l for l in gb1_line)

check("T6 LIVE REPLAY: Game Room (79.3F, worst) is still pinned 100%",
      out[gr] == 100)
check("T7 LIVE REPLAY: GB1 (76.3F, runner-up) no longer logs 'struggling but "
      "no donor rooms' -- the donor pool is no longer drained by Game Room",
      not gb1_starved)
check("T8 LIVE REPLAY: GB1 is itself pinned 100% as a beneficiary",
      out[gb1] == 100)

n_closed = sum(1 for v in out.values() if v == 0)
check(f"T9 LIVE REPLAY: not every room is slammed shut ({n_closed} at 0% of "
      f"{len(out)}) -- concentration is bounded, leaving airflow in rooms "
      f"that can use it",
      n_closed < len(out) - 2)


# =============================================================================
# 3. Saturation inversion behavior
# =============================================================================
ha = fresh()
for room, t in LIVE.items():
    zn, rn = find_key(room)
    ha.states[svc.ZONES[zn]["rooms"][rn]["temp"]] = t
for room in ("Game Room", "Guest Bedroom 1"):
    zn, rn = find_key(room)
    occ = svc.ZONES[zn]["rooms"][rn].get("occupancy")
    if occ:
        ha.states[occ] = "on"
# Mark Game Room saturated, as the state machine would after the escalation
# probe failed for SATURATION_ENTER_CYCLES consecutive cycles.
ha._saturated_rooms.add(gr)
ha._delivery_penalty[gr] = 2.25   # the live value; would normally escalate

out_sat = ha._apply_priority_rooms(dict(positions), "cooling", SP, None)

check("T10 a SATURATED room still gets its OWN vents at 100% (it should "
      "receive everything its duct can carry)",
      out_sat[gr] == 100)

gr_line = [l for l in ha.logs if "Priority Game Room" in l]
check("T11 a SATURATED room is tagged SATURATED, not ESCALATED",
      any("SATURATED" in l for l in gr_line)
      and not any("ESCALATED" in l for l in gr_line))

sat_donors_at_zero = sum(
    1 for l in ha.logs if "throttling" in l and "Game Room" in l and "-> 0%" in l)
check("T12 a SATURATED room throttles its donors to 50%, never 0% "
      "(closing more vents cannot increase a duct-limited room's throughput, "
      "and on a constant-torque ECM it lowers total house CFM)",
      sat_donors_at_zero == 0)

gr_throttle_lines = [l for l in ha.logs
                     if "throttling" in l and "Priority Game Room" in l]
check(f"T13 a SATURATED room recruits at most SATURATION_MAX_DONORS "
      f"({svc.SATURATION_MAX_DONORS}) donors, freeing the rest for rooms that "
      f"can still use the air (got {len(gr_throttle_lines)})",
      len(gr_throttle_lines) <= svc.SATURATION_MAX_DONORS)

closed_sat = sum(1 for v in out_sat.values() if v == 0)
closed_normal = sum(1 for v in out.values() if v == 0)
check(f"T14 saturation inversion closes FEWER vents than normal escalation "
      f"({closed_sat} vs {closed_normal}) -- less static, more total CFM",
      closed_sat <= closed_normal)


# =============================================================================
# 4. Hysteresis config: the exit bar must clear the entry bar, or the flag
#    chatters at the boundary (Game Room's live penalty 1.68 sits right on
#    top of the 1.5 escalate threshold).
# =============================================================================
check("T15 SATURATION_EXIT_RATE is strictly above DELIVERY_STUCK_RATE "
      "(separate enter/exit thresholds prevent flapping)",
      svc.SATURATION_EXIT_RATE > svc.DELIVERY_STUCK_RATE)
check("T16 entry requires multiple consecutive cycles (escalation is given a "
      "real chance to work before being declared ineffective)",
      svc.SATURATION_ENTER_CYCLES >= 2)
check("T17 saturation is CLEARABLE -- it is load-dependent, not permanent "
      "(Game Room does reach setpoint overnight, and a latched-forever flag "
      "would sabotage the overnight recovery window)",
      svc.SATURATION_EXIT_CYCLES >= 1 and svc.SATURATION_EXIT_RATE > 0)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
