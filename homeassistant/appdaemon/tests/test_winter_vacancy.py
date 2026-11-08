"""Winter vacancy/PIR policy regressions (2026-11-08).

Covers the heating-only vacant-room floor and the sleeping-occupant PIR
override:

  - A room in a VACANT zone is not actively heated above HEAT_VACANT_FLOOR_F
    (58F); at/below the floor it gets 100%. It never recruits donor air.
  - On an OCCUPIED floor, a room that reads empty is treated as occupied once
    it is HEAT_PIR_OVERRIDE_F (1.5F) below the heat setpoint, so a sleeping
    occupant is not closed out.
  - Main Bedroom is a heating beneficiary (donor_only disabled for heating);
    Cat Room stays donor-only in both seasons.

No pytest / appdaemon needed: same stub pattern as the other suites.
"""
import os
import sys
import types
from datetime import datetime, timedelta

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

APPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps")
sys.path.insert(0, APPS_DIR)
import smart_vent_controller as svc  # noqa: E402

svc.SETPOINT_NUDGE_ENABLED = True

PASS = []
def check(label, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + label)


class FakeHA(svc.SmartVentController):
    def __init__(self, action="heating", mode="heat_cool",
                 sp_cool=72.0, sp_heat=64.0,
                 clock=datetime(2026, 11, 9, 2, 0, 0)):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self.calls = []
        self.logs = []
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
        self._room_last_occupied = {}
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
        self._fan_assist_active = False
        self._cooling_ended_at = None
        self._last_hvac_action = None
        for _zn, zone in svc.ZONES.items():
            for _rn, sensors in zone["rooms"].items():
                self.states[sensors["temp"]] = 66.0
                if sensors.get("occupancy"):
                    self.states[sensors["occupancy"]] = "off"
                for vent in sensors.get("vents", []):
                    self.attrs[(vent, "current_tilt_position")] = 100
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
        self.attrs[(svc.FAN_ENTITY, "fan_mode")] = "auto"
        self.attrs[(svc.WEATHER_ENTITY, "temperature")] = 40.0

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

    def stamp_zone(self, zone, occupied):
        if occupied:
            self._zone_last_occupied[zone] = self._clock
        else:
            self._zone_last_occupied[zone] = self._clock - timedelta(minutes=30)


def auto(ha):
    return ha._auto_calculate("heat_cool", "heating", 72.0, 64.0)


# =============================================================================
# 1. Vacant zone: floor at 58F
# =============================================================================
ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
check("T1 vacant zone, empty room 62F -> 0% (above 58F floor)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 57.5)
check("T1 vacant zone, empty room 57.5F -> 100% (at/below floor)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

# Sleeping-occupant safety net: a room whose own PIR fired in the last 10h is
# not floor-treated just because the zone went vacant.
ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=2))
check("T1 vacant zone, room occupied 2h ago at 62F -> 100% (sleep safety net)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=11))
check("T1 vacant zone, no motion for 11h at 62F -> 0% (floor applies)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

# =============================================================================
# 2. Occupied floor: PIR override at 1.5F
# =============================================================================
ha = FakeHA()
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 62.4)   # need 1.6F
check("T2 occupied zone, empty room 1.6F below -> 100% (sleeping override)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

ha = FakeHA()
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 62.5)   # need exactly 1.5F
check("T2 occupied zone, empty room exactly 1.5F below -> 50% (trickle)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 50)

ha = FakeHA()
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 63.5)   # need 0.5F
check("T2 occupied zone, empty room 0.5F below -> 0% (fresh cycle, closed)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

# The PIR trigger must use the RAW gap; downstairs `need` carries the +2F
# heat-rise bonus and would otherwise trip while the room is above setpoint.
ha = FakeHA()
ha.stamp_zone("downstairs", True)
ha.set_room("downstairs", "Main Bedroom", 64.5)    # 0.5F ABOVE heat sp
check("T2 downstairs empty room above setpoint is not PIR-overridden to 100",
      auto(ha)[("downstairs", "Main Bedroom")] != 100)

ha = FakeHA()
ha.stamp_zone("downstairs", True)
ha.set_room("downstairs", "Main Bedroom", 62.6)    # 1.4F below, under PIR 1.5
check("T2 downstairs empty room 1.4F below is not 100% (bonus guard)",
      auto(ha)[("downstairs", "Main Bedroom")] == 50)

# =============================================================================
# 3. Priority pass: vacant rooms never recruit donors; occupied-floor
#    sleeping rooms do.
# =============================================================================
ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 57.5)
ha.set_room("downstairs", "Kitchen", 68.0)
base = auto(ha)
out = ha._apply_priority_rooms(dict(base), "heating", 72.0, 64.0, "Auto")
check("T3 vacant cold room gets its own 100% but no donor recruitment",
      out[("upstairs", "Guest Bedroom 1")] == 100
      and not any("Priority Guest Bedroom 1" in l for l in ha.logs))

ha = FakeHA()
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0)   # 4F below, reads empty
ha.set_room("downstairs", "Kitchen", 68.0)
base = auto(ha)
out = ha._apply_priority_rooms(dict(base), "heating", 72.0, 64.0, "Auto")
check("T3 occupied-floor sleeping room becomes a priority beneficiary",
      out[("upstairs", "Guest Bedroom 1")] == 100
      and any("Priority Guest Bedroom 1" in l for l in ha.logs)
      and out[("downstairs", "Kitchen")] in (0, 50))

# =============================================================================
# 4. donor_only seasonality: Main Bedroom yes in heating, Cat Room no.
# =============================================================================
ha = FakeHA()
ha.stamp_zone("downstairs", True)
ha.set_room("downstairs", "Main Bedroom", 60.0, occ=True)
ha.set_room("downstairs", "Living Room", 68.0, occ=True)
base = auto(ha)
out = ha._apply_priority_rooms(dict(base), "heating", 72.0, 64.0, "Auto")
check("T4 Main Bedroom is a heating beneficiary (donor_only disabled)",
      out[("downstairs", "Main Bedroom")] == 100
      and any("Priority Main Bedroom" in l for l in ha.logs))

ha = FakeHA()
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Cat Room", 60.0, occ=True)
ha.set_room("downstairs", "Living Room", 68.0, occ=True)
base = auto(ha)
out = ha._apply_priority_rooms(dict(base), "heating", 72.0, 64.0, "Auto")
check("T4 Cat Room stays donor-only in heating (no priority pin)",
      not any("Priority Cat Room" in l for l in ha.logs))

# =============================================================================
# 5. Fan assist: no blower for a vacant floor; sleeping room on an occupied
#    floor can engage it.
# =============================================================================
ha = FakeHA(action="idle")
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0)
ha.set_room("downstairs", "Living Room", 68.0)
ha._apply_fan_assist({}, "Auto", "idle", 72.0, 64.0)
check("T5 vacant floor does not engage fan assist",
      not any(s == "ecobee_enhanced/set_fan_hold" for s, _ in ha.calls))

ha = FakeHA(action="idle")
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0)
ha.set_room("downstairs", "Living Room", 68.0)
ha._apply_fan_assist({}, "Auto", "idle", 72.0, 64.0)
check("T5 sleeping room on an occupied floor can engage fan assist",
      any(s == "ecobee_enhanced/set_fan_hold" for s, _ in ha.calls))

# =============================================================================
# 6. Setpoint nudge: vacant floors cannot drive a house-wide heat nudge;
#    occupied-floor rooms can.
# =============================================================================
ha = FakeHA(action="heating")
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0)
ha._apply_setpoint_nudge("heat_cool", "heating", 72.0, 64.0, "Auto")
check("T6 vacant floor cannot drive a heat setpoint nudge",
      not any(s == "ecobee_enhanced/set_hold_temperature" for s, _ in ha.calls))

ha = FakeHA(action="heating")
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0)
ha._apply_setpoint_nudge("heat_cool", "heating", 72.0, 64.0, "Auto")
check("T6 occupied-floor cold room can drive a heat setpoint nudge",
      any(s == "ecobee_enhanced/set_hold_temperature" for s, _ in ha.calls))

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
