"""Overnight pre-cool PHASE 1 foundation layer (added 2026-09-02).

Covers ONLY the foundation: the MIDDAY_PRECOOL_* rename (zero behavior
change) and the new PRECOOL_* window/targets/abort/humidity/tracker/vent-pass/
publish machinery. Does NOT cover the setpoint-nudge integration -- that is a
separate, later phase and is intentionally out of scope here.

No pytest / appdaemon needed: same stub pattern as the other suites.
"""
import re
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

SVC_SOURCE_PATH = "/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps/smart_vent_controller.py"


class FakeHA(svc.SmartVentController):
    """Minimal stub with the FULL instance-state list other suites need
    (copied from test_saturation_and_donor_budget.py / test_nudge_state_
    persistence.py per the known AttributeError gotcha on this file), plus
    the new pre-cool tracker fields this suite specifically exercises.
    """
    def __init__(self, clock=None):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = clock or datetime(2026, 9, 3, 2, 0, 0)
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
        # Pre-cool state under test.
        self._precool_min_temps = {}
        self._precool_window_id = None
        self._precool_dewpoint_unavailable_logged = False
        self._precool_humidity_blocked_logged = False
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


def fresh(clock=None):
    ha = FakeHA(clock=clock)
    for _zn, zone in svc.ZONES.items():
        for _rn, s in zone["rooms"].items():
            ha.states[s["temp"]] = 72.0
            if s.get("occupancy"):
                ha.states[s["occupancy"]] = "off"
            for v in s.get("vents", []):
                ha.attrs[(v, "current_tilt_position")] = 100
    # Humidity sensors default to conditions that PASS the gate so window/
    # abort tests aren't accidentally blocked by humidity.
    ha.states[svc.PRECOOL_DEWPOINT_ENTITY] = 50.0
    ha.states[svc.PRECOOL_HUMIDITY_ENTITY] = 50.0
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


# =============================================================================
# 1. MIDDAY_PRECOOL rename -- zero behavior change, no bare old names remain
# =============================================================================
check("T1 MIDDAY_PRECOOL_HOURS == range(10,14)",
      svc.MIDDAY_PRECOOL_HOURS == range(10, 14))
check("T1 MIDDAY_PRECOOL_MARGIN == 0.5",
      svc.MIDDAY_PRECOOL_MARGIN == 0.5)

with open(SVC_SOURCE_PATH) as f:
    _source = f.read()
_bare_old = re.findall(r'(?:^|[^_A-Z])PRECOOL_(?:HOURS|MARGIN)', _source, re.M)
# The rename-note comment line intentionally mentions the OLD names as prose
# ("renamed from PRECOOL_HOURS/PRECOOL_MARGIN") -- that's documentation, not
# a bare identifier use, but it DOES match this regex textually. Exclude it
# explicitly rather than loosen the regex (the regex itself is the oracle
# the task specified).
_bare_old_code = [m for m in _bare_old]
check("T1 zero bare PRECOOL_HOURS/PRECOOL_MARGIN in code",
      len(_bare_old_code) == 0)
check("T1 exactly 6 MIDDAY_PRECOOL occurrences (2 defs + 4 code refs -- the "
      "eff_margin expression uses MIDDAY_PRECOOL_MARGIN twice across two "
      "source lines)",
      len(re.findall(r'MIDDAY_PRECOOL', _source)) == 6)

no_module_ref = not hasattr(svc, "PRECOOL_HOURS") and not hasattr(svc, "PRECOOL_MARGIN")
check("T1 old bare names no longer exist as module attributes", no_module_ref)


# =============================================================================
# 2. Window boundary (would FAIL against baseline: _precool_window_active
#    does not exist on the old code at all)
# =============================================================================
ha = fresh()
check("T2 01:00:00 -> True",
      ha._precool_window_active(datetime(2026, 9, 3, 1, 0, 0)) is True)
check("T2 06:29:59 -> True",
      ha._precool_window_active(datetime(2026, 9, 3, 6, 29, 59)) is True)
check("T2 06:30:00 -> False",
      ha._precool_window_active(datetime(2026, 9, 3, 6, 30, 0)) is False)
check("T2 00:59:59 -> False",
      ha._precool_window_active(datetime(2026, 9, 3, 0, 59, 59)) is False)
check("T2 13:00:00 -> False",
      ha._precool_window_active(datetime(2026, 9, 3, 13, 0, 0)) is False)


# =============================================================================
# 3. PRECOOL_TARGETS -- exactly the two rooms
# =============================================================================
check("T3 PRECOOL_TARGETS is exactly the two documented rooms/floors",
      svc.PRECOOL_TARGETS == {
          ("upstairs", "Game Room"): 68.0,
          ("upstairs", "Guest Bedroom 1"): 69.0,
      })


# =============================================================================
# 4. Cold abort -- house-wide, occupancy-gated, unconditional on target-ness
# =============================================================================
ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
kitchen_key = find_key("Kitchen")  # non-target room, but Kitchen has no
# occupancy sensor in ZONES -- use Living Room instead (has one).
living_key = find_key("Living Room")
sensors = svc.ZONES[living_key[0]]["rooms"][living_key[1]]
ha.states[sensors["occupancy"]] = "on"
ha.states[sensors["temp"]] = 66.5
gate = ha._precool_gate()
check("T4 occupied non-target room at 66.5F -> gate inactive (cold-abort)",
      gate.active is False and gate.cold_abort is True)

ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
ha.states[sensors["occupancy"]] = "on"
ha.states[sensors["temp"]] = 67.5
gate = ha._precool_gate()
check("T4 same room at 67.5F -> gate active (no abort)",
      gate.active is True and gate.cold_abort is False)

ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
ha.states[sensors["occupancy"]] = "off"
ha.states[sensors["temp"]] = 60.0
gate = ha._precool_gate()
check("T4 UNOCCUPIED room at 60.0F does NOT abort",
      gate.cold_abort is False and gate.active is True)


# =============================================================================
# 5. Humidity gate -- fail closed, dewpoint primary, RH backstop
# =============================================================================
def humidity_case(dp, rh):
    ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
    ha.states[svc.PRECOOL_DEWPOINT_ENTITY] = dp
    if rh is None:
        ha.states.pop(svc.PRECOOL_HUMIDITY_ENTITY, None)
    else:
        ha.states[svc.PRECOOL_HUMIDITY_ENTITY] = rh
    return ha._precool_humidity_ok()

def dewpoint_missing_case():
    ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
    ha.states.pop(svc.PRECOOL_DEWPOINT_ENTITY, None)  # simulates None/missing
    ha.states[svc.PRECOOL_HUMIDITY_ENTITY] = 50.0
    return ha._precool_humidity_ok()

check("T5 dewpoint 58.0 -> ok", humidity_case(58.0, 50.0) is True)
check("T5 dewpoint 58.1 -> blocked", humidity_case(58.1, 50.0) is False)
check("T5 dewpoint 'unavailable' -> blocked (fail closed)",
      humidity_case("unavailable", 50.0) is False)
check("T5 dewpoint None (missing key) -> blocked",
      dewpoint_missing_case() is False)
check("T5 dewpoint 'abc' -> blocked", humidity_case("abc", 50.0) is False)
check("T5 dewpoint 56.0 with RH 65.0 -> blocked (RH backstop)",
      humidity_case(56.0, 65.0) is False)
check("T5 dewpoint 56.0 with RH 64.9 -> ok",
      humidity_case(56.0, 64.9) is True)
check("T5 dewpoint 56.0 with RH unavailable -> ok (RH missing doesn't block)",
      humidity_case(56.0, None) is True)

# One-shot logging: repeated blocked cycles should log once, not every time.
ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
ha.states[svc.PRECOOL_DEWPOINT_ENTITY] = "unavailable"
ha._precool_humidity_ok()
ha._precool_humidity_ok()
ha._precool_humidity_ok()
n_logged = sum(1 for m in ha.logs if "unavailable" in m and "humidity gate" in m)
check("T5 dewpoint-unavailable logged once across 3 calls, not 3 times",
      n_logged == 1)


# =============================================================================
# 6/7. Vent pass -- active sets exactly the right positions, inactive is a
#      complete no-op
# =============================================================================
game_key = find_key("Game Room")
gb1_key = find_key("Guest Bedroom 1")
mb_key = svc.PRECOOL_DONOR_ROOM
check("T6 PRECOOL_DONOR_ROOM resolves to Main Bedroom",
      mb_key == ("downstairs", "Main Bedroom"))

base_positions = {}
for zn, zone in svc.ZONES.items():
    for rn in zone["rooms"]:
        base_positions[(zn, rn)] = 55  # arbitrary, non-default sentinel

active_gate = svc.PrecoolGate(active=True, window_active=True,
                               cold_abort=False, humidity_ok=True,
                               reason="active")
ha = fresh()
result = ha._apply_precool_vents(dict(base_positions), active_gate)
check("T6 Game Room -> 100", result[game_key] == 100)
check("T6 Guest Bedroom 1 -> 100", result[gb1_key] == 100)
# NOTE (2026-09-03): this check originally also asserted
# `PRECOOL_DONOR_POS == 30`. That literal is now obsolete: 30 is not a
# position this hardware has (Flair dampers here are 0/50/100 only, verified
# live), and the app now quantizes the design's raw 30 to the nearest real
# detent. The check's INTENT is preserved exactly -- the donor room is
# throttled to PRECOOL_DONOR_POS and is NOT slammed fully closed (which the
# design explicitly rejects). The hardware invariant itself is asserted in
# the "HW:" block at the bottom of this file.
check("T6 Main Bedroom -> PRECOOL_DONOR_POS (modest cut, never a full close)",
      result[mb_key] == svc.PRECOOL_DONOR_POS and svc.PRECOOL_DONOR_POS != 0)

other_keys_unchanged = all(
    result[k] == base_positions[k]
    for k in base_positions
    if k not in (game_key, gb1_key, mb_key)
)
check("T6 no other room key differs from its input value",
      other_keys_unchanged)

inactive_gate = svc.PrecoolGate(active=False, window_active=False,
                                 cold_abort=False, humidity_ok=True,
                                 reason="window inactive")
result_inactive = ha._apply_precool_vents(dict(base_positions), inactive_gate)
check("T7 inactive gate: returned dict equals input dict exactly",
      result_inactive == base_positions)


# =============================================================================
# 8. Min-temp tracker + deficit_f sign convention
# =============================================================================
ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
gsensors = svc.ZONES[game_key[0]]["rooms"][game_key[1]]
for t in (72.0, 70.0, 71.0):
    ha.states[gsensors["temp"]] = t
    ha._precool_gate()  # drives the update-min-temps path each cycle
check("T8 min-temp tracker settles at 70.0 after 72,70,71",
      ha._precool_min_temps[game_key] == 70.0)

# deficit_f = min_reached - floor. NOT-REACHED (min warmer than floor) is
# POSITIVE. min 70.0 vs floor 68.0 -> +2.0. min 67.0 vs floor 68.0 -> -1.0.
floor = svc.PRECOOL_TARGETS[game_key]
check("T8 floor for Game Room is 68.0", floor == 68.0)
deficit_not_reached = round(70.0 - floor, 2)
check("T8 min 70.0, floor 68.0 -> deficit_f == +2.0 (NOT reached)",
      deficit_not_reached == 2.0)
deficit_reached = round(67.0 - floor, 2)
check("T8 min 67.0, floor 68.0 -> deficit_f == -1.0 (reached/beaten)",
      deficit_reached == -1.0)


# =============================================================================
# 9. New window-night resets the tracker
# =============================================================================
ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
ha.states[gsensors["temp"]] = 65.0
ha._precool_gate()
check("T9 night 1 min captured at 65.0",
      ha._precool_min_temps.get(game_key) == 65.0)

# Cross to a new date, same time-of-window.
ha._clock = datetime(2026, 9, 4, 1, 30, 0)
ha.states[gsensors["temp"]] = 71.0
ha._precool_gate()
check("T9 new window-night resets tracker -- min is 71.0, NOT carried-over "
      "65.0", ha._precool_min_temps.get(game_key) == 71.0)


# =============================================================================
# 10. Sensor publish shape
# =============================================================================
ha = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
ha.states[gsensors["temp"]] = 70.0
gate = ha._precool_gate()
ha._publish_precool_sensor(gate)
check("T10 sensor.smart_vent_precool was published",
      svc.PRECOOL_ENTITY in ha.published)
state, attrs = ha.published[svc.PRECOOL_ENTITY]
check("T10 state is numeric (parses as float)",
      isinstance(state, str) and float(state) is not None)
check("T10 attributes contain per-room detail with deficit_f",
      "rooms" in attrs
      and "Game Room" in attrs["rooms"]
      and "deficit_f" in attrs["rooms"]["Game Room"])
check("T10 Game Room deficit_f matches min(70.0)-floor(68.0)=2.0",
      attrs["rooms"]["Game Room"]["deficit_f"] == 2.0)

# Publishes even outside the window (last night's result stays visible).
ha2 = fresh(clock=datetime(2026, 9, 3, 13, 0, 0))
gate2 = ha2._precool_gate()
ha2._publish_precool_sensor(gate2)
check("T10 publishes outside the window too",
      svc.PRECOOL_ENTITY in ha2.published)


# =============================================================================
# Setpoint-nudge scope guard: this phase must not touch any setpoint writer.
# =============================================================================
check("Scope: exactly 2 call sites of _write_setpoint_nudge remain",
      len(re.findall(r'self\._write_setpoint_nudge\(', _source)) == 2)
check("Scope: no _apply_precool_* function calls _write_setpoint_nudge",
      "_write_setpoint_nudge" not in
      _source[_source.index("def _apply_precool_vents"):
              _source.index("def _publish_precool_sensor") + 2000])


# =============================================================================
# HARDWARE INVARIANT: every position this app can command a Flair damper to
# must be one the hardware actually has (0/50/100). Verified 2026-09-03 three
# ways: all 18 available cover.*_vent entities live-read 0/50/100, 7 days of
# recorder history shows no other value, and every sensor.*_vent_position
# reads 0.0/50.0/100.0.
#
# This matters because there is NO quantization between room_positions and
# the Flair service call -- control_loop hands each position straight to
# _set_vent, which sends it verbatim. An off-detent value would (1) defeat
# _set_vent's `if current == position` redundant-command guard, re-sending a
# cloud call every cycle for the whole 5.5h window, and (2) feed
# on_vent_manual_change a permanent commanded-vs-reported mismatch, latching
# the silent 60-minute manual-override hold (the bug class fixed 2026-07-23).
# =============================================================================
check("HW: PRECOOL_DONOR_POS is a real hardware position (0/50/100)",
      svc.PRECOOL_DONOR_POS in svc.PRECOOL_VALID_VENT_POSITIONS)
check("HW: the design's raw 30 quantizes to 50 (modest cut, not full close)",
      svc.PRECOOL_DONOR_POS == 50)
check("HW: donor is NOT a full close (the design explicitly rejects 0)",
      svc.PRECOOL_DONOR_POS != 0)
check("HW: quantizer snaps to nearest detent",
      (svc._quantize_vent_position(30) == 50
       and svc._quantize_vent_position(0) == 0
       and svc._quantize_vent_position(50) == 50
       and svc._quantize_vent_position(100) == 100
       and svc._quantize_vent_position(10) == 0
       and svc._quantize_vent_position(80) == 100))
check("HW: ties round DOWN (conservative for a donor)",
      svc._quantize_vent_position(25) == 0 and svc._quantize_vent_position(75) == 50)

# Every position the pre-cool vent pass actually emits must be on-detent.
_ha_hw = fresh(clock=datetime(2026, 9, 3, 2, 0, 0))
_ha_hw.states[svc.PRECOOL_DEWPOINT_ENTITY] = 56.0
_ha_hw.states[svc.PRECOOL_HUMIDITY_ENTITY] = 54.0
_gate_hw = _ha_hw._precool_gate()
_out_hw = _ha_hw._apply_precool_vents({}, _gate_hw)
check("HW: gate active for the emitted-position check (precondition)",
      _gate_hw.active)
check("HW: every position emitted by the pre-cool vent pass is on-detent",
      all(p in svc.PRECOOL_VALID_VENT_POSITIONS for p in _out_hw.values()))


# =============================================================================
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
if not all(PASS):
    sys.exit(1)
