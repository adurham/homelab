"""Winter-readiness regressions for the smart vent controller (2026-11-08).

Covers the seasonal gate on overnight pre-cool and the heating-axis fix in
the zone-presence sensor. Before this change, `_precool_gate()` had no idea
what season it was: in heating it stayed active, pinned Game Room / Guest
Bedroom 1 to 100%, and its cooling-signed demand could drive a HEAT setpoint
nudge (raising the heat setpoint to "pre-cool" a warm room).

No pytest / appdaemon needed: same stub pattern as the other suites.
"""
import os
import sys
import types
from datetime import datetime

# ---- stub appdaemon BEFORE importing the controller --------------------------
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")
class _Hass:
    def __init__(self, *a, **k): pass
hassapi.Hass = _Hass
for _mn, _m in [("appdaemon", types.ModuleType("appdaemon")),
                ("appdaemon.plugins", types.ModuleType("appdaemon.plugins")),
                ("appdaemon.plugins.hass", types.ModuleType("appdaemon.plugins.hass"))]:
    sys.modules[_mn] = _m
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

# Portable path (the older suites in this directory hardcode a macOS checkout).
APPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps")
sys.path.insert(0, APPS_DIR)
import smart_vent_controller as svc  # noqa: E402

svc.SETPOINT_NUDGE_ENABLED = True

PASS = []
def check(label, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + label)


class FakeHA(svc.SmartVentController):
    """Minimal full-state stub (same shape as test_precool_foundation.py)."""
    def __init__(self, action="heating", mode="heat_cool", outdoor=40.0,
                 sp_cool=72.0, sp_heat=64.0,
                 clock=datetime(2026, 11, 9, 2, 0, 0)):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = clock
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        self._last_zone_positions = {}
        self._last_positions = {}
        self._manual_holds = {}
        self._saturation_streak = {}
        self._saturated_rooms = set()
        self._saturation_recover = {}
        self._zone_last_occupied = {}
        self._zone_occupied = {}
        self._zone_vacancy_demoted = set()
        self._sp_owned = False
        self._sp_commanded_cool = None
        self._sp_commanded_heat = None
        self._sp_baseline_cool = None
        self._sp_baseline_heat = None
        self._sp_last_write_ts = None
        self._sp_mismatch_since = None
        self._sp_heating = None
        self._sp_override_cooldown_until = None
        self._sp_truth_unavailable_logged = False
        self._precool_min_temps = {}
        self._precool_window_id = None
        self._precool_dewpoint_unavailable_logged = False
        self._precool_humidity_blocked_logged = False
        self._precool_suppressed_window_id = None
        self._nudge_persist_disable = True
        self._nudge_state_file = None
        self._nudge_restore_pending = False
        self.calls = []
        self.logs = []
        for _zn, zone in svc.ZONES.items():
            for _rn, sensors in zone["rooms"].items():
                self.states[sensors["temp"]] = 66.0
                if sensors.get("occupancy"):
                    self.states[sensors["occupancy"]] = "off"
                for vent in sensors.get("vents", []):
                    self.attrs[(vent, "current_tilt_position")] = 100
        self.states[svc.PRECOOL_DEWPOINT_ENTITY] = 40.0
        self.states[svc.PRECOOL_HUMIDITY_ENTITY] = 50.0
        self.attrs[(svc.WEATHER_ENTITY, "temperature")] = outdoor
        self.attrs[(svc.THERMOSTAT, "all")] = {
            "state": mode,
            "attributes": {
                "hvac_mode": mode,
                "hvac_action": action,
                "target_temp_high": sp_cool,
                "target_temp_low": sp_heat,
                "current_temperature": 67.0,
            },
        }
        self.states[svc.SETPOINT_TRUTH_COOL] = sp_cool
        self.states[svc.SETPOINT_TRUTH_HEAT] = sp_heat

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

    def call_service(self, service, **kwargs):
        self.calls.append((service, kwargs))

    def set_room(self, zone, room, temp, occ=False):
        sensors = svc.ZONES[zone]["rooms"][room]
        self.states[sensors["temp"]] = temp
        if sensors.get("occupancy"):
            self.states[sensors["occupancy"]] = "on" if occ else "off"


# =============================================================================
# 1. Seasonal gate: pre-cool must never be active in heating.
# =============================================================================
for label, kwargs, want in [
    ("heating action in heat_cool, 40F outdoor -> inactive",
     dict(action="heating", mode="heat_cool", outdoor=40.0), False),
    ("heating action wins even at 90F outdoor -> inactive",
     dict(action="heating", mode="heat_cool", outdoor=90.0), False),
    ("explicit heat mode, idle action, 90F -> inactive",
     dict(action="idle", mode="heat", outdoor=90.0), False),
    ("heat_cool idle, 55F outdoor -> inactive (season)",
     dict(action="idle", mode="heat_cool", outdoor=55.0), False),
    ("heat_cool idle, 75F outdoor -> active (summer control)",
     dict(action="idle", mode="heat_cool", outdoor=75.0), True),
    ("cooling action, 55F outdoor -> active (explicit cooling)",
     dict(action="cooling", mode="heat_cool", outdoor=55.0), True),
]:
    ha = FakeHA(**kwargs)
    gate = ha._precool_gate(hvac_action=kwargs["action"],
                            hvac_mode=kwargs["mode"])
    check(label, gate.active is want)


# =============================================================================
# 2. Heating demand is zero and cannot write a heat setpoint hold.
# =============================================================================
ha = FakeHA(action="heating", mode="heat_cool", outdoor=40.0)
ha.set_room("upstairs", "Game Room", 70.0)
ha.set_room("upstairs", "Guest Bedroom 1", 69.0)
gate = ha._precool_gate(hvac_action="heating", hvac_mode="heat_cool")
check("T2 heating precool_demand == 0.0 even above the floors",
      ha._precool_demand(gate) == 0.0)
ha._apply_setpoint_nudge("heat_cool", "heating", 72.0, 64.0, "Auto",
                         precool_gate=gate)
holds = [kw for svc_name, kw in ha.calls
         if svc_name == "ecobee_enhanced/set_hold_temperature"]
check("T2 heating precool writes NO setpoint hold", holds == [])


# =============================================================================
# 3. Defense in depth: an active (forged) gate still no-ops in heating.
# =============================================================================
ha = FakeHA(action="heating", mode="heat_cool", outdoor=40.0)
forged = svc.PrecoolGate(active=True, window_active=True, cold_abort=False,
                         humidity_ok=True, reason="forged", suppressed=False)
before = {("upstairs", "Game Room"): 0, ("upstairs", "Guest Bedroom 1"): 0}
after = ha._apply_precool_vents(dict(before), forged, heating=True)
check("T3 heating vent pass is a no-op even with an active gate",
      after == before)


# =============================================================================
# 4. Zone-presence sensor publishes the HEATING contention axis in winter.
# =============================================================================
ha = FakeHA(action="heating", mode="heat_cool", outdoor=40.0)
ha.set_room("upstairs", "Game Room", 60.0, occ=True)
ha._update_zone_presence()
state, attrs = ha.published[svc.ZONE_PRESENCE_ENTITY]
check("T4 heating contention is published (not the cooling axis)",
      state == "occupied-contention" and attrs["max_contention"] > 0.0)

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
