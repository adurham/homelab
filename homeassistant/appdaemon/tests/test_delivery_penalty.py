"""Standalone validation of the delivery-penalty (achieved-cooling-rate) axis.

No pytest / appdaemon needed: we stub appdaemon.plugins.hass.hassapi with a
fake Hass base whose get_state/set_state/datetime are backed by a dict and a
controllable clock, then drive _update_delivery_penalties / _room_margin /
_apply_priority_rooms directly. Exercises the exact GB2 scenario plus the
double-count and decay guarantees.
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
        self.states = {}          # entity -> state
        self.attrs = {}           # (entity, attr) -> value
        self.published = {}       # entity -> (state, attributes)
        self._clock = datetime(2026, 6, 5, 15, 0, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        self.logs = []
    def datetime(self, aware=False):
        return self._clock
    def advance(self, minutes):
        self._clock += timedelta(minutes=minutes)
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
    # set every room's air temp comfortably AT setpoint, vents open, occupancy off
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

SP = 72.0  # cool setpoint
GB2 = "Guest Bedroom 2"

# ---- Test 1: GB2 well-supplied, wide open, occupied, hot, NOT moving -> penalty accrues
ha = fresh()
k = find_key(ha, GB2)
tk = svc.ZONES[k[0]]["rooms"][GB2]["temp"]
ha.states[svc.ZONES[k[0]]["rooms"][GB2]["occupancy"]] = "on"
ha._supply_penalty[k] = 0.0          # good supply air
ha.states[tk] = 76.0                 # 4F over setpoint
# cycle 1: establishes baseline (no prev sample yet)
ha._update_delivery_penalties("cooling", SP, None)
check("T1 first cycle sets no penalty (needs a prior sample)", ha._delivery_penalty.get(k, 0.0) == 0.0)
# cycle 2..4: 2 min apart, temp barely moves (stuck) -> penalty should climb
for _ in range(3):
    ha.advance(2)
    ha.states[tk] = ha.states[tk] - 0.01   # ~0.005 F/min, below STUCK_RATE
    ha._update_delivery_penalties("cooling", SP, None)
check("T1 stuck GB2 accrues delivery penalty > 0", ha._delivery_penalty[k] > 0.0)
print("    GB2 delivery penalty:", round(ha._delivery_penalty[k], 3))

# ---- Test 2: penalty lowers the activation margin (engages earlier)
base_margin = svc.PRIORITY_MARGIN_BASE
ha._supply_penalty[k] = 0.0
m = ha._room_margin(k, heating=False)
check("T2 delivery penalty pulls margin below base", m < base_margin)
print("    margin:", round(m, 3), "(base", base_margin, ")")

# ---- Test 3: well-supplied room that IS cooling normally accrues NO penalty
ha2 = fresh()
k3 = find_key(ha2, GB2)
tk3 = svc.ZONES[k3[0]]["rooms"][GB2]["temp"]
ha2.states[svc.ZONES[k3[0]]["rooms"][GB2]["occupancy"]] = "on"
ha2._supply_penalty[k3] = 0.0
ha2.states[tk3] = 76.0
ha2._update_delivery_penalties("cooling", SP, None)
for _ in range(3):
    ha2.advance(2)
    ha2.states[tk3] = ha2.states[tk3] - 0.5   # 0.25 F/min, healthy
    ha2._update_delivery_penalties("cooling", SP, None)
check("T3 a normally-cooling room accrues ~0 penalty", ha2._delivery_penalty.get(k3, 0.0) < 0.01)

# ---- Test 4: anti-double-count — a room with HIGH supply penalty (GB1-type)
#      does NOT also accrue delivery penalty (supply axis owns it)
ha4 = fresh()
k4 = find_key(ha4, "Guest Bedroom 1")
tk4 = svc.ZONES[k4[0]]["rooms"]["Guest Bedroom 1"]["temp"]
ha4.states[svc.ZONES[k4[0]]["rooms"]["Guest Bedroom 1"]["occupancy"]] = "on"
ha4._supply_penalty[k4] = 5.0        # warm supply: supply axis already owns it
ha4.states[tk4] = 78.0
ha4._update_delivery_penalties("cooling", SP, None)
for _ in range(3):
    ha4.advance(2)
    ha4.states[tk4] = ha4.states[tk4] - 0.01   # stuck, but warm-supplied
    ha4._update_delivery_penalties("cooling", SP, None)
check("T4 warm-supply room does NOT double-count into delivery penalty",
      ha4._delivery_penalty.get(k4, 0.0) < 0.01)

# ---- Test 5: decay — once GB2 starts moving, penalty trends to zero
ha._supply_penalty[k] = 0.0
start = ha._delivery_penalty[k]
for _ in range(8):
    ha.advance(2)
    ha.states[tk] = ha.states[tk] - 0.6   # now cooling well
    ha._update_delivery_penalties("cooling", SP, None)
check("T5 penalty decays once room recovers", ha._delivery_penalty[k] < start)
print("    penalty after recovery:", round(ha._delivery_penalty[k], 3), "(was", round(start,3), ")")

# ---- Test 6: throttled vent (not wide open) -> NOT counted as delivery-stuck
ha6 = fresh()
k6 = find_key(ha6, GB2)
tk6 = svc.ZONES[k6[0]]["rooms"][GB2]["temp"]
ha6.states[svc.ZONES[k6[0]]["rooms"][GB2]["occupancy"]] = "on"
ha6._supply_penalty[k6] = 0.0
for v in svc.ZONES[k6[0]]["rooms"][GB2]["vents"]:
    ha6.attrs[(v, "current_tilt_position")] = 50   # throttled, not wide open
ha6.states[tk6] = 76.0
ha6._update_delivery_penalties("cooling", SP, None)
for _ in range(3):
    ha6.advance(2)
    ha6.states[tk6] = ha6.states[tk6] - 0.01
    ha6._update_delivery_penalties("cooling", SP, None)
check("T6 throttled (not wide-open) room accrues no delivery penalty",
      ha6._delivery_penalty.get(k6, 0.0) < 0.01)

# ---- Test 7: summary sensor published with numeric state + attributes
check("T7 delivery-handicap summary sensor published",
      svc.DELIVERY_PENALTY_ENTITY in ha.published)
print("    published state:", ha.published.get(svc.DELIVERY_PENALTY_ENTITY))

# ---- Test 8: escalation flag set for a delivery-handicapped beneficiary
ha8 = fresh()
k8 = find_key(ha8, GB2)
tk8 = svc.ZONES[k8[0]]["rooms"][GB2]["temp"]
ha8.states[svc.ZONES[k8[0]]["rooms"][GB2]["occupancy"]] = "on"
ha8._supply_penalty[k8] = 0.0
ha8._delivery_penalty[k8] = svc.DELIVERY_ESCALATE_PENALTY + 0.2  # handicapped
ha8.states[tk8] = 74.0   # 2F over, below the 4F PRIORITY_ESCALATE_OVER threshold
# give a clearly-cooler donor room so beneficiaries logic has something to chew
donor = find_key(ha8, "Cat Room")
ha8.states[svc.ZONES[donor[0]]["rooms"]["Cat Room"]["temp"]] = 70.0
positions = {}
for zn, zone in svc.ZONES.items():
    for rn in zone["rooms"]:
        positions[(zn, rn)] = 100
out = ha8._apply_priority_rooms(dict(positions), "cooling", SP, None)
# the donor (Cat Room) should be throttled to ESCALATED pos (0), not 50,
# because GB2 is delivery-handicapped even though only 2F over.
catpos = out[donor]
check("T8 delivery handicap forces donor escalation (0%) below 4F-over",
      catpos == svc.PRIORITY_DONOR_POS_ESCALATED)
print("    Cat Room donor position:", catpos,
      "(escalated", svc.PRIORITY_DONOR_POS_ESCALATED, "vs normal", svc.PRIORITY_DONOR_POS, ")")

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
