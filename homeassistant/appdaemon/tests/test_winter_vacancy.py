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
        self._room_sleep_hold_until = {}
        self._room_pir_latch_until = {}
        self._activity_entity_to_key = {}
        for _zn, zone in svc.ZONES.items():
            for _rn, sensors in zone["rooms"].items():
                for entity in sensors.get("activity", []):
                    self._activity_entity_to_key[entity] = (_zn, _rn)
        self._house_away_since = self._clock - timedelta(minutes=90)
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
        for entity in svc.HOUSE_PERSON_ENTITIES:
            self.states[entity] = "not_home"
        self.states[svc.HOUSE_CO2_ENTITY] = 500.0
        for _zn, zone in svc.ZONES.items():
            for _rn, sensors in zone["rooms"].items():
                for entity in sensors.get("activity", []):
                    self.states[entity] = "off"

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

    def set_house(self, home):
        for entity in svc.HOUSE_PERSON_ENTITIES:
            self.states[entity] = "home" if home else "not_home"
        self._house_away_since = (None if home
                                  else self._clock - timedelta(minutes=90))

    def set_co2(self, ppm):
        self.states[svc.HOUSE_CO2_ENTITY] = ppm

    def set_activity(self, zone, room, on):
        for entity in svc.ZONES[zone]["rooms"][room].get("activity", []):
            self.states[entity] = "on" if on else "off"

    def set_all_duct_temps(self, temp):
        for _zn, zone in svc.ZONES.items():
            for _rn, sensors in zone["rooms"].items():
                for vent in sensors.get("vents", []):
                    self.states[self._duct_sensor_for_vent(vent)] = temp


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

# Sleep rooms use a higher floor: setpoint 64 - 4F = 60F.
ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 59.5)
check("T1 sleep room 59.5F -> 100% (60F sleep floor)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

ha = FakeHA()
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 60.5)
check("T1 sleep room 60.5F -> 0% (above 60F sleep floor)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

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
    ha.datetime() - timedelta(hours=13))
check("T1 vacant zone, no motion for 13h at 62F -> 0% (floor applies)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

# Daytime hold is 2h (not 12h), so the 2 PM example still gets its savings.
ha = FakeHA(clock=datetime(2026, 11, 10, 14, 0, 0))
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=5))
check("T1 daytime: 5h since motion at 62F -> 0% (4h sleep day hold expired)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

ha = FakeHA(clock=datetime(2026, 11, 10, 14, 0, 0))
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=1))
check("T1 daytime: 1h since motion at 62F -> 100% (2h day hold active)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

# The 58F floor is HOUSE-AWAY only. Room occupancy is motion-only, so while
# anyone is home a still person must never be floored.
ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=11))
check("T1 house home: vacant room 62F is not floored (PIR trigger heats it)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 63.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=11))
check("T1 house home: vacant room 1F below is closed, not floored (0%)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

# CO2 is a physiological signal: elevated CO2 (someone breathing, e.g. a
# guest) vetoes the floor even when the phones are away and motion is quiet.
ha = FakeHA()
ha.set_house(False)
ha.set_co2(900.0)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=13))
check("T1 elevated CO2 vetoes the floor; room gets PIR heat (100%)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

# A bedroom light/fan on while someone is home is non-PIR evidence of use.
ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 63.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=13))
ha.set_activity("upstairs", "Guest Bedroom 1", True)
check("T1 activity on + house home: 1F below gets 50% (occupied), not floored",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 50)

# Guest/untracked occupant: activity on must veto the floor even when the
# phones say away.
ha = FakeHA()
ha.set_house(False)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    ha.datetime() - timedelta(hours=13))
ha.set_activity("upstairs", "Guest Bedroom 1", True)
check("T1 activity on + house away is not floored (guest safety)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

# Lights-out sleep cue: a bedroom light/fan/TV turning off in the evening
# holds the room as occupied until 10:30, per room.
ha = FakeHA(clock=datetime(2026, 11, 9, 23, 0, 0))
ha.set_house(True)
ha.on_activity_change("light.main_bedroom_ceiling_fan_light", None,
                      "on", "off", {})
ha._clock = datetime(2026, 11, 10, 2, 0, 0)
check("T1 bedroom lights-out holds the room occupied at 2am",
      ha._room_recently_occupied(("downstairs", "Main Bedroom")) is True)
ha._clock = datetime(2026, 11, 10, 11, 0, 0)
check("T1 bedroom lights-out hold expires at 10:30",
      ha._room_recently_occupied(("downstairs", "Main Bedroom")) is False)

# A common-area light going off does not set a sleep hold.
ha = FakeHA(clock=datetime(2026, 11, 9, 23, 0, 0))
ha.set_house(True)
ha.on_activity_change("switch.living_room_accent_lights", None,
                      "on", "off", {})
ha._clock = datetime(2026, 11, 10, 2, 0, 0)
check("T1 common-area lights-out does not set a sleep hold",
      ha._room_recently_occupied(("downstairs", "Living Room")) is False)

# The sleep cue is inactive while the house is away.
ha = FakeHA(clock=datetime(2026, 11, 9, 23, 0, 0))
ha.set_house(False)
ha.on_activity_change("light.main_bedroom_ceiling_fan_light", None,
                      "on", "off", {})
ha._clock = datetime(2026, 11, 10, 2, 0, 0)
check("T1 away: lights-out still sets a sleep hold (guest safety)",
      ha._room_recently_occupied(("downstairs", "Main Bedroom")) is True)

# 09:00 cliff regression: a 23:00 PIR protects through 10:30 the next
# morning, even though the old rule switched to a 2h daytime hold at 09:00.
ha = FakeHA(clock=datetime(2026, 11, 10, 9, 5, 0))
ha.set_house(False)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    datetime(2026, 11, 9, 23, 0, 0))
check("T1 09:05 after a 23:00 PIR is NOT floored (protected to 10:30)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

ha = FakeHA(clock=datetime(2026, 11, 10, 10, 45, 0))
ha.set_house(False)
ha.stamp_zone("upstairs", False)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha._room_last_occupied[("upstairs", "Guest Bedroom 1")] = (
    datetime(2026, 11, 9, 23, 0, 0))
check("T1 10:45 after a 23:00 PIR IS floored (10:30 expiry)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 0)

# House-away must be stable for HOUSE_AWAY_DEBOUNCE_MIN before it counts.
ha = FakeHA()
ha.set_house(False)
ha._house_away_since = ha._clock
check("T1 house-away debounce: not away immediately",
      ha._house_away() is False)
ha._clock += timedelta(minutes=61)
check("T1 house-away debounce: away after 61 min",
      ha._house_away() is True)

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

# 1.5F trigger latches for 20 min so the vent cannot chatter at the boundary.
ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 62.4)   # 1.6F below
auto(ha)
check("T2b 1.6F below latches the room as occupied",
      ha._room_pir_latched(("upstairs", "Guest Bedroom 1")) is True)
ha._clock += timedelta(minutes=21)
check("T2b PIR latch expires after 20 minutes",
      ha._room_pir_latched(("upstairs", "Guest Bedroom 1")) is False)

# A dead/unavailable PIR must never make a room look empty in heating.
ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 62.0)
ha.states[svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]["occupancy"]] = "unavailable"
check("T2b unavailable PIR fails safe to occupied (not floored)",
      auto(ha)[("upstairs", "Guest Bedroom 1")] == 100)

# A sleeping bedroom must not be used as a donor by the priority pass.
ha = FakeHA()
ha.set_house(True)
ha.stamp_zone("upstairs", True)
ha.stamp_zone("downstairs", True)
ha.set_room("upstairs", "Guest Bedroom 1", 60.0, occ=True)
ha.set_room("downstairs", "Main Bedroom", 64.0, occ=False)
ha._room_sleep_hold_until[("downstairs", "Main Bedroom")] = (
    ha._clock + timedelta(hours=1))
base = auto(ha)
out = ha._apply_priority_rooms(dict(base), "heating", 72.0, 64.0, "Auto")
check("T2b sleeping Main Bedroom is not throttled as a donor",
      out[("downstairs", "Main Bedroom")] == 50
      and not any("throttling downstairs/Main Bedroom" in l for l in ha.logs))

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


# =============================================================================
# 7. Heating backpressure: 40% static, 25% hot supply, force-open at emergency.
# =============================================================================
def all_closed():
    return {(zn, rn): 0 for zn, z in svc.ZONES.items() for rn in z["rooms"]}


def closed_vents(out):
    return sum(len(svc.ZONES[z]["rooms"][r].get("vents", []))
               for (z, r), p in out.items() if p == 0)


ha = FakeHA(action="heating")
ha.set_all_duct_temps(100.0)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T7 heating backpressure caps closures at 40%",
      closed_vents(out) <= 8)

ha = FakeHA(action="heating")   # no duct samples
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T7 no supply sample caps heating closures at 25%",
      closed_vents(out) <= 5)

ha = FakeHA(action="heating")
ha.set_all_duct_temps(140.0)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T7 heating supply emergency opens all closed vents",
      closed_vents(out) == 0)

ha = FakeHA(action="heating")
ha.set_all_duct_temps(130.0)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T7 hot supply lowers the heating cap to 25%",
      closed_vents(out) <= 5)

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
