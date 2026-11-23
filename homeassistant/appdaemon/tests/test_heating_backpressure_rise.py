"""Offline test: heating backpressure fires on the duct-air RISE, not an
absolute supply temperature.

Why this file exists (2026-11-23): the heating guard was written against
125F/135F absolute supply thresholds, which the house never reaches — the first
season the gas furnace actually ran, every aux call peaked at 103.2-103.6F
supply against a 64F house, so both thresholds were dead code. The furnace's own
manual states its limit as a RISE (Z9ET080C16: 25-55F at low fire, 40-70F at
high fire), so the guard now measures rise over the room-temp mean. These checks
pin the bands, the fallbacks, and the arithmetic.
"""
import os
import sys
import types
from datetime import datetime

# ── Stub the appdaemon import chain ────────────────────────────────────────────
ad = types.ModuleType("appdaemon")
plugins = types.ModuleType("appdaemon.plugins")
hassmod = types.ModuleType("appdaemon.plugins.hass")
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")


class _Hass:  # minimal base class
    def __init__(self, *a, **k):
        pass


hassapi.Hass = _Hass
sys.modules["appdaemon"] = ad
sys.modules["appdaemon.plugins"] = plugins
sys.modules["appdaemon.plugins.hass"] = hassmod
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

_APPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps")
if not os.path.isdir(_APPS):
    _APPS = "/home/adam.durham/repos/homelab/homeassistant/appdaemon/apps"
sys.path.insert(0, _APPS)
import smart_vent_controller as svc  # noqa: E402

NOW = datetime(2026, 11, 23, 8, 10, 0)
PASS = []


def check(name, ok):
    PASS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


class Fake(svc.SmartVentController):
    """Controller with the two measured inputs replaced by seeded numbers."""

    def __init__(self, supply, return_t, equipment=None):
        self._supply = supply
        self._return_t = return_t
        self._equipment = equipment
        self._heat_guard_level = None
        # Coil-feedback state the cooling path reads when a cycle is not heating.
        self._coil_emergency_latched = False
        self._coil_emergency_since = None
        self._coil_ratio_current = None
        self._coil_ratio_changed_at = None
        self._cooling_started_at = None
        self._coil_sensor_fail_count = 0
        self.logs = []
        self.published = {}

    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def datetime(self, aware=False):
        return NOW

    def get_state(self, entity, attribute=None):
        if entity == svc.EQUIPMENT_STATUS_ENTITY:
            return self._equipment
        return None

    def _heating_supply_max(self):
        return self._supply

    def _room_temp_mean(self):
        return self._return_t

    def set_state(self, entity, state=None, attributes=None, **k):
        self.published[entity] = (state, attributes or {})


def all_closed():
    return {(zn, rn): 0 for zn, z in svc.ZONES.items() for rn in z["rooms"]}


def closed_vents(out):
    return sum(len(svc.ZONES[z]["rooms"][r].get("vents", []))
               for (z, r), p in out.items() if p == 0)


def total_vents():
    return len(svc._get_all_vents())


TOTAL = total_vents()
CAP_40 = int(TOTAL * svc.MAX_CLOSED_RATIO_HEATING)
CAP_25 = int(TOTAL * svc.MAX_CLOSED_RATIO_HEATING_WARN)
print(f"({TOTAL} vents: 40% cap = {CAP_40} closed, 25% cap = {CAP_25} closed)\n")

# =============================================================================
# 1. The bands, using today's real numbers.
# =============================================================================
ha = Fake(supply=103.4, return_t=63.9)          # 39.5F rise — the hottest aux call
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T1 real gas-heat rise (39.5F) keeps the full 40% closure budget",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

ha = Fake(supply=94.8, return_t=64.0)           # 30.8F rise — the heat pump call
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T1 real heat-pump rise (30.8F) keeps the full 40% closure budget",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

ha = Fake(supply=112.0, return_t=66.0)          # 46.0F rise — airflow going short
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T1 a 46F rise tightens the heating cap to 25%",
      closed_vents(out) <= CAP_25)

ha = Fake(supply=118.0, return_t=66.0)          # 52.0F rise — past the low-fire rating
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T1 a 52F rise force-opens every closed vent",
      closed_vents(out) == 0)

# =============================================================================
# 2. Rise, not absolute: the same duct temp must read differently at two house
#    temperatures. This is the case the old 125F absolute threshold got wrong.
# =============================================================================
ha = Fake(supply=124.0, return_t=72.0)          # 52F rise, 124F absolute
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T2 124F supply in a 72F house is 52F of rise — emergency fires where the "
      "old 125F absolute threshold would have stayed at 40%",
      closed_vents(out) == 0)

ha = Fake(supply=116.0, return_t=72.0)          # 44F rise, warm house
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T2 116F supply in a 72F house is only 44F of rise — no throttle",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

# =============================================================================
# 3. Fallbacks fail conservative, never permissive.
# =============================================================================
ha = Fake(supply=None, return_t=64.0)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 no open-vent supply sample caps closures at 25%",
      closed_vents(out) <= CAP_25)

ha = Fake(supply=120.0, return_t=None)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 no readable room temps (no rise) caps closures at 25%",
      closed_vents(out) <= CAP_25)

# =============================================================================
# 4. Arithmetic + publication.
# =============================================================================
ha = Fake(supply=103.4, return_t=63.9)
supply, rise = ha._heating_rise()
check("T4 _heating_rise returns the hottest vent minus the room mean",
      supply == 103.4 and abs(rise - 39.5) < 1e-6)

ha = Fake(supply=103.4, return_t=None)
check("T4 _heating_rise reports (supply, None) with no return proxy",
      ha._heating_rise() == (103.4, None))

ha = Fake(supply=103.4, return_t=63.9)
ha._publish_heating_supply()
state, attrs = ha.published[svc.HEATING_SUPPLY_ENTITY]
check("T4 the supply sensor publishes supply_max_f, return_proxy_f and rise_f",
      state == "103.4"
      and attrs.get("supply_max_f") == 103.4
      and abs(attrs.get("return_proxy_f") - 63.9) < 1e-6
      and abs(attrs.get("rise_f") - 39.5) < 1e-6)

# =============================================================================
# 5. Latching: opening vents drops the rise, so the guard must not release
#    mid-call and let the vents close again.
# =============================================================================
ha = Fake(supply=112.0, return_t=66.0)          # 46F rise -> warn
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T5 a 46F rise throttles to 25% and latches",
      closed_vents(out) <= CAP_25 and ha._heat_guard_level == "warn")

ha._supply = 95.0                                # rise falls back to 29F mid-call
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T5 the latch holds after the rise falls back (no flap back to 40%)",
      closed_vents(out) <= CAP_25 and ha._heat_guard_level == "warn")

out = ha._apply_backpressure_rooms(all_closed(), "idle")
check("T5 a non-heating cycle clears the latch for the next call",
      ha._heat_guard_level is None)

out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T5 the next heat call starts clean and gets the 40% budget back",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

# =============================================================================
# 6. Gas high fire: never observed here, so hold the tighter budget regardless
#    of the measured rise.
# =============================================================================
ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat2")
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 gas high fire (auxHeat2) caps closures at 25% even at a normal rise",
      closed_vents(out) <= CAP_25)

ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat1")
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 gas low fire (auxHeat1) keeps the 40% budget",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

ha = Fake(supply=103.4, return_t=63.9, equipment="unknown")
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 an unknown equipment status falls through to the rise guard",
      closed_vents(out) <= CAP_40 and closed_vents(out) > CAP_25)

# =============================================================================
# 7. The retired absolute thresholds must not creep back.
# =============================================================================
check("T7 the old absolute thresholds are gone (guard cannot regress silently)",
      not hasattr(svc, "HEAT_SUPPLY_WARN_F")
      and not hasattr(svc, "HEAT_SUPPLY_EMERGENCY_F"))
check("T7 the rise thresholds are ordered sensibly vs the manual's 55F low-fire band",
      svc.HEAT_RISE_WARN_F < svc.HEAT_RISE_EMERGENCY_F <= 55.0)

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
