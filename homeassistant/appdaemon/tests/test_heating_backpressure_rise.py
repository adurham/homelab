"""Offline test: the vent controller's airflow enclosure is per equipment state.

The house runs one blower in six states — cooling low/high, heat-pump heat
low/high, gas low fire/high fire — and each has its own airflow and its own
limit. This file pins:

  * the resolver (form from the thermostat, tap from the air-handler watts),
  * the per-state enclosure (closure cap + duct-air rise bands),
  * the fail-safe rule that an unreadable input always resolves to the LOW tap,
    and an unreadable equipment_status to the tightest heat budget,
  * the latches, so opening a vent cannot release the guard mid-call.

Numbers behind the measured rows (2026-11-23): gas low fire peaked at 103.2-
103.6F supply against a 63.8-64.0F house = 39.5F rise on the LO HEAT tap
(388 W); the heat pump peaked at 30.8F on the same Medium tap (415 W); the top
tap is ~650 W. Furnace ratings: 25-55F rise at low fire, 40-70F at high fire
(JCI tech guide Table 2, Z9ET080C16).
"""
import os
import sys
import types
from datetime import datetime, timedelta

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
    """Controller with the measured inputs replaced by seeded numbers."""

    def __init__(self, supply=None, return_t=66.0, equipment=None,
                 watts=None, watts_age_s=0.0, coil=50.0):
        self._supply = supply
        self._return_t = return_t
        self._equipment = equipment
        self._watts = watts
        self._watts_age = watts_age_s
        self._coil = coil
        self._heat_guard_level = None
        self._room_need = {}
        self._room_occupied = {}
        self._bp_clamped = False
        self._scorecard = {}
        # Coil-feedback state the cooling path reads when a cycle is not heating.
        self._coil_emergency_latched = False
        self._coil_emergency_since = None
        self._coil_ratio_current = None
        self._coil_ratio_changed_at = None
        self._cooling_started_at = NOW - timedelta(seconds=1200)
        self._coil_sensor_fail_count = 0
        self.logs = []
        self.published = {}

    # --- HA shims -------------------------------------------------------------
    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def datetime(self, aware=False):
        return NOW

    def parse_datetime(self, stamp):
        return datetime.fromisoformat(stamp)

    def get_state(self, entity, attribute=None):
        if entity == svc.EQUIPMENT_STATUS_ENTITY:
            return self._equipment
        if entity == svc.EQUIPMENT_POWER_ENTITY:
            if attribute == "last_updated":
                return (NOW - timedelta(seconds=self._watts_age)).isoformat()
            return None if self._watts is None else str(self._watts)
        if entity == svc.COIL_TEMP_SENSOR:
            return None if self._coil is None else str(self._coil)
        return None

    def get_history(self, entity, **k):
        return []          # coil "stuck" check sees no history -> not stuck

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


TOTAL = len(svc._get_all_vents())
CAP = {k: int(TOTAL * v["cap"]) for k, v in svc.EQUIP_STATES.items()}
CAP_25 = int(TOTAL * svc.MAX_CLOSED_RATIO_HEATING_WARN)
print(f"({TOTAL} vents; caps: {CAP})\n")

# =============================================================================
# 1. The resolver: form from the thermostat, tap from the blower watts.
# =============================================================================
def resolve(action, equipment=None, watts=None, age=0.0):
    return Fake(equipment=equipment, watts=watts, watts_age_s=age)._equipment_state(action)


check("T1 cooling at 415W resolves to the low cooling tap",
      resolve("cooling", watts=415)[0] == "cool_low")
check("T1 cooling at 650W resolves to the high cooling tap",
      resolve("cooling", watts=650)[0] == "cool_high")
check("T1 heat pump at 415W resolves to the low heat-pump tap",
      resolve("heating", "fan,heatPump", 415)[0] == "hp_heat_low")
check("T1 heat pump at 650W resolves to the high heat-pump tap",
      resolve("heating", "fan,heatPump", 650)[0] == "hp_heat_high")
check("T1 gas stage 1 at 388W resolves to gas low fire",
      resolve("heating", "fan,auxHeat1", 388)[0] == "gas_low")
check("T1 gas stage 2 resolves to gas high fire even at LO HEAT watts",
      resolve("heating", "fan,auxHeat2", 388)[0] == "gas_high")
check("T1 heating with an unreadable equipment_status is heat_unknown",
      resolve("heating", "unknown", 650)[0] == "heat_unknown")
check("T1 idle resolves to idle",
      resolve("idle", "unknown", 232)[0] == "idle")

# =============================================================================
# 2. Fail-safe: unreadable or stale inputs fall to the LOW (tighter) tap.
# =============================================================================
check("T2 no blower meter at all -> low tap, not high",
      resolve("cooling", watts=None)[0] == "cool_low")
check("T2 a stale blower reading (>10 min) is ignored -> low tap",
      resolve("cooling", watts=650, age=svc.BLOWER_STALE_SEC + 60)[0] == "cool_low")
check("T2 a fresh blower reading is trusted -> high tap",
      resolve("cooling", watts=650, age=60)[0] == "cool_high")
check("T2 gas at 650W with stage-1 only still counts as a high tap",
      resolve("heating", "fan,auxHeat1", 650)[0] == "gas_high")

# =============================================================================
# 3. Heating: measured rows get their real rise bands and closure budget.
# =============================================================================
ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 real gas low-fire rise (39.5F) keeps the 40% budget",
      closed_vents(out) <= CAP["gas_low"] and closed_vents(out) > CAP_25)

ha = Fake(supply=94.8, return_t=64.0, equipment="fan,heatPump", watts=415)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 real heat-pump rise (30.8F) keeps the 40% budget",
      closed_vents(out) <= CAP["hp_heat_low"] and closed_vents(out) > CAP_25)

ha = Fake(supply=112.0, return_t=66.0, equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 a 46F rise throttles to 25%",
      closed_vents(out) <= CAP_25)

ha = Fake(supply=118.0, return_t=66.0, equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 a 52F rise force-opens every closed vent",
      closed_vents(out) == 0)

ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat2", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 gas high fire holds the 25% budget at a normal low-fire rise",
      closed_vents(out) <= CAP["gas_high"])

ha = Fake(supply=103.4, return_t=63.9, equipment="unknown", watts=650)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T3 an unknown heat form holds the 25% budget",
      closed_vents(out) <= CAP["heat_unknown"])

# =============================================================================
# 4. Rise, not absolute supply temperature (the old 125F/135F pair was dead).
# =============================================================================
ha = Fake(supply=124.0, return_t=72.0, equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T4 124F supply in a 72F house is 52F of rise -> emergency",
      closed_vents(out) == 0)

ha = Fake(supply=116.0, return_t=72.0, equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T4 116F supply in a 72F house is 44F of rise -> no throttle",
      closed_vents(out) <= CAP["gas_low"] and closed_vents(out) > CAP_25)

# =============================================================================
# 5. Fallbacks fail conservative, never permissive.
# =============================================================================
ha = Fake(supply=None, return_t=64.0, equipment="fan,heatPump", watts=415)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T5 no open-vent supply sample caps closures at 25%",
      closed_vents(out) <= CAP_25)

ha = Fake(supply=120.0, return_t=None, equipment="fan,heatPump", watts=415)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T5 no readable room temps (no rise) caps closures at 25%",
      closed_vents(out) <= CAP_25)

# =============================================================================
# 6. Latches: opening vents drops the rise, so the guard must not flap.
# =============================================================================
ha = Fake(supply=112.0, return_t=66.0, equipment="fan,heatPump", watts=415)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 a 46F rise throttles to 25% and latches",
      closed_vents(out) <= CAP_25 and ha._heat_guard_level == "warn")

ha._supply = 95.0
out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 the latch holds after the rise falls back",
      closed_vents(out) <= CAP_25 and ha._heat_guard_level == "warn")

ha._apply_backpressure_rooms(all_closed(), "idle")
check("T6 a non-heating cycle clears the latch",
      ha._heat_guard_level is None)

out = ha._apply_backpressure_rooms(all_closed(), "heating")
check("T6 the next heat call starts clean and gets its budget back",
      closed_vents(out) <= CAP["hp_heat_low"] and closed_vents(out) > CAP_25)

# =============================================================================
# 7. Cooling: the suction guard still governs, but the state caps what it may
#    argue for. LO COOL is 1175 CFM on a 5-ton coil (235 CFM/ton) -> 60% max.
# =============================================================================
ha = Fake(equipment=None, watts=415, coil=50.0)   # healthy coil, low tap
out = ha._apply_backpressure_rooms(all_closed(), "cooling")
check("T7 a healthy coil on the LOW cooling tap is held to 60% closed",
      closed_vents(out) <= CAP["cool_low"])

ha = Fake(equipment=None, watts=650, coil=50.0)   # healthy coil, top tap
out = ha._apply_backpressure_rooms(all_closed(), "cooling")
check("T7 a healthy coil on the HIGH cooling tap may use the 80% ceiling",
      closed_vents(out) <= CAP["cool_high"] and closed_vents(out) > CAP["cool_low"])

ha = Fake(equipment=None, watts=None, coil=None)  # no feedback at all
out = ha._apply_backpressure_rooms(all_closed(), "cooling")
check("T7 no coil feedback and no meter stays at the static 60%",
      closed_vents(out) <= int(TOTAL * svc.MAX_CLOSED_RATIO))

# An idle cycle must NOT inherit the unknown-heat 25% budget: manual modes
# (Cool Upstairs/Downstairs) close vents between calls on purpose.
ha = Fake(equipment="unknown", watts=232, coil=None)
out = ha._apply_backpressure_rooms(all_closed(), "idle")
check("T7 an idle cycle keeps the historical 60% static ceiling",
      closed_vents(out) <= int(TOTAL * svc.MAX_CLOSED_RATIO)
      and closed_vents(out) > CAP_25)

ha = Fake(equipment="unknown", watts=232)
ha._publish_equipment_state("idle")
state, attrs = ha.published[svc.EQUIP_STATE_ENTITY]
check("T7 the idle publish reports the static cap, not the heat budget",
      state == "idle" and attrs.get("closed_cap") == svc.MAX_CLOSED_RATIO)

# =============================================================================
# 8. Arithmetic, publication, and the retired thresholds.
# =============================================================================
ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat1", watts=388)
supply, rise = ha._heating_rise()
check("T8 _heating_rise returns the hottest vent minus the room mean",
      supply == 103.4 and abs(rise - 39.5) < 1e-6)

check("T8 _heating_rise reports (supply, None) with no return proxy",
      Fake(supply=103.4, return_t=None)._heating_rise() == (103.4, None))

ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat1", watts=388)
ha._publish_heating_supply()
state, attrs = ha.published[svc.HEATING_SUPPLY_ENTITY]
check("T8 the supply sensor publishes supply_max_f, return_proxy_f and rise_f",
      state == "103.4" and attrs.get("supply_max_f") == 103.4
      and abs(attrs.get("return_proxy_f") - 63.9) < 1e-6
      and abs(attrs.get("rise_f") - 39.5) < 1e-6)

ha = Fake(supply=103.4, return_t=63.9, equipment="fan,auxHeat1", watts=388)
ha._publish_equipment_state("heating")
state, attrs = ha.published[svc.EQUIP_STATE_ENTITY]
check("T8 the equipment-state sensor names the form, tap and enclosure",
      state == "gas_low" and attrs.get("tap") == "low"
      and attrs.get("blower_w") == 388.0
      and attrs.get("closed_cap") == svc.EQUIP_STATES["gas_low"]["cap"]
      and attrs.get("measured") is True)

check("T8 the old absolute thresholds are gone",
      not hasattr(svc, "HEAT_SUPPLY_WARN_F")
      and not hasattr(svc, "HEAT_SUPPLY_EMERGENCY_F"))
_heat_states = {s: p for s, p in svc.EQUIP_STATES.items()
                if s.startswith(("hp_heat", "gas", "heat_"))}
check("T8 no unmeasured HEATING state is more permissive than a measured one",
      all(p["cap"] <= max(v["cap"] for v in _heat_states.values() if v["measured"])
          for s, p in _heat_states.items() if not p["measured"]))
check("T8 the high cooling tap is the only state allowed more rope than its "
      "low tap, and it stays under the hard ceiling (live coil feedback governs)",
      svc.EQUIP_STATES["cool_high"]["cap"] > svc.EQUIP_STATES["cool_low"]["cap"]
      and svc.EQUIP_STATES["cool_high"]["cap"] <= svc.MAX_CLOSED_RATIO_HARD_CEILING)
check("T8 the rise bands are ordered and inside the manual's low-fire rating",
      svc.HEAT_RISE_WARN_F < svc.HEAT_RISE_EMERGENCY_F <= 55.0)

# =============================================================================
# 9. Budget accounting: offline vents are spent, and reopening is need-ranked.
# =============================================================================
class FakeOffline(Fake):
    """Fake whose first N vents read 'unavailable' (a Flair dropout)."""

    def __init__(self, offline_vents, **kw):
        super().__init__(**kw)
        self._offline = set(svc._get_all_vents()[:offline_vents])

    def get_state(self, entity, attribute=None):
        if attribute is None and entity in self._offline:
            return "unavailable"
        return super().get_state(entity, attribute)


ha = FakeOffline(0, equipment="fan,auxHeat1", watts=388)
check("T9 no offline vents -> offline count is 0", ha._offline_vent_count() == 0)

ha = FakeOffline(3, equipment="fan,auxHeat1", watts=388)
check("T9 three offline vents are counted as unavailable",
      ha._offline_vent_count() == 3)

# 3 offline + a 40% budget (8) leaves only 5 vents that may be COMMANDED closed.
ha = FakeOffline(3, supply=103.4, return_t=63.9,
                 equipment="fan,auxHeat1", watts=388)
out = ha._apply_backpressure_rooms(all_closed(), "heating")
commanded = closed_vents(out)
check("T9 offline vents consume the closure budget (8 allowed -> 5 commanded)",
      commanded <= CAP["gas_low"] - 3)

# Reopen order: the room that is behind must come back first.
_rooms = [("upstairs", "Guest Bathroom"), ("downstairs", "Hallway"),
          ("downstairs", "Main Bathroom")]
_positions = {k: 0 for k in _rooms}
_needs = {_rooms[0]: 4.0, _rooms[1]: 1.0, _rooms[2]: -1.0}
ha = Fake(equipment="fan,auxHeat1", watts=388)
out = ha._open_closed_rooms_for_backpressure(_positions, 1, "test", need_map=_needs)
check("T9 the room with the highest need is reopened first",
      out[_rooms[0]] == 50 and out[_rooms[1]] == 50 and out[_rooms[2]] == 0)

# No need on record (Manual mode): still caps, never crashes, and does not
# pretend to rank.
_positions = {k: 0 for k in _rooms}
ha = Fake(equipment="fan,auxHeat1", watts=388)
out = ha._open_closed_rooms_for_backpressure(_positions, 1, "test", need_map={})
check("T9 an empty need map still caps closures at the budget",
      sum(1 for v in out.values() if v == 0) <= 1)

# =============================================================================
# 10. Occupancy outranks the floor mirror in the heating ladder.
# =============================================================================
check("T10 the heating occupancy weight beats the +2F floor bonus",
      svc.HEAT_OCC_NEED_BONUS > svc.UPSTAIRS_HEAT_RISE_BONUS)

# =============================================================================
# 11. Outcome scorecard: what the house actually did, independent of the passes.
# =============================================================================
class FakeScore(Fake):
    """Fake whose room temps and occupancy are seeded directly."""

    def __init__(self, temps, occ, **kw):
        super().__init__(**kw)
        self._temps_override = temps
        self._room_occupied = occ

    def _read_temp(self, entity):
        return self._temps_override.get(entity)


Z = svc.ZONES["upstairs"]["rooms"]
D = svc.ZONES["downstairs"]["rooms"]
gb1 = Z["Guest Bedroom 1"]["temp"]        # occupied, 4F behind
gb2 = Z["Guest Bedroom 2"]["temp"]        # occupied, 1F behind
kit = D["Kitchen"]["temp"]                # vacant, 6F behind

_temps = {gb1: 60.0, gb2: 63.0, kit: 52.0}
_occ = {("upstairs", "Guest Bedroom 1"): True,
        ("upstairs", "Guest Bedroom 2"): True,
        ("downstairs", "Kitchen"): False}

ha = FakeScore(_temps, _occ, equipment="fan,auxHeat1", watts=388)
ha._publish_scorecard("heating", 72.0, 64.0)
state, attrs = ha.published[svc.SCORECARD_ENTITY]
check("T11 occupancy-weighted error averages only the occupied rooms",
      abs(attrs["occ_err_f"] - 2.5) < 1e-6 and state == "2.5")
check("T11 rooms_behind counts occupied rooms past the deadband (4F is, 1F is not)",
      attrs["rooms_behind"] == "1" and attrs["rooms_occupied_scored"] == "2")
check("T11 worst vacant drift is the vacant room's own error",
      abs(attrs["worst_vacant_drift_f"] - 12.0) < 1e-6)
check("T11 spread is warmest minus coldest readable room",
      abs(attrs["spread_f"] - 11.0) < 1e-6)
check("T11 degree-hours accumulate at the error x cycle time",
      abs(float(attrs["occ_degf_h_today"])
          - round(2.5 * svc.CYCLE_INTERVAL / 3600.0, 2)) < 1e-6)

ha._publish_scorecard("heating", 72.0, 64.0)
state2, attrs2 = ha.published[svc.SCORECARD_ENTITY]
check("T11 a second cycle doubles the degree-hour accumulator",
      abs(float(attrs2["occ_degf_h_today"])
          - round(2 * 2.5 * svc.CYCLE_INTERVAL / 3600.0, 2)) < 1e-6)

ha._bp_clamped = True
ha._publish_scorecard("heating", 72.0, 64.0)
_, attrs3 = ha.published[svc.SCORECARD_ENTITY]
check("T11 a cycle where the budget bound adds a minute to the cap counter",
      abs(float(attrs3["cap_bound_min_today"]) - svc.CYCLE_INTERVAL / 60.0) < 1e-6)
check("T11 the clamp flag is cleared after it is scored", ha._bp_clamped is False)

from datetime import date as _date
ha._scorecard = {"day": _date(2026, 11, 22), "occ_degf_h": 99.0, "cap_min": 99.0}
ha._publish_scorecard("heating", 72.0, 64.0)
_, attrs4 = ha.published[svc.SCORECARD_ENTITY]
check("T11 a new local day resets the accumulators",
      abs(float(attrs4["occ_degf_h_today"])
          - round(2.5 * svc.CYCLE_INTERVAL / 3600.0, 2)) < 1e-6
      and float(attrs4["cap_bound_min_today"]) == 0.0)

ha = FakeScore(_temps, _occ, equipment="fan,auxHeat1", watts=105.0)
ha._publish_scorecard("idle", 72.0, 64.0)
state5, attrs5 = ha.published[svc.SCORECARD_ENTITY]
check("T11 an idle cycle reports no error rather than a zero",
      state5 == "unknown" and attrs5["occ_err_f"] is None)

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
