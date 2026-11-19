"""Guard: the comfort-driven setpoint nudge (worst_excess -> +/-2F on the ecobee) is OFF in
production (2026-11-18) while the PRE-COOL demand source keeps working.

Why: the HH860E2S11 is a Gen 1 inverter heat pump with one compressor input; ecobee stage 2
never changes its power, the ecobee is single-stage on the heat pump, so the nudge only drags the
whole-house target colder. This test pins the production default and proves the pre-cool path
(a different mechanism: deliberate overnight cooling) is untouched. Offline, no appdaemon needed.
"""
import json
import os
import re
import sys
import tempfile
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

# Portable path (resolved from this file; SVC_APPS_DIR still overrides).
APPS_DIR = os.environ.get(
    "SVC_APPS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps"))
sys.path.insert(0, APPS_DIR)
import smart_vent_controller as svc  # noqa: E402

SVC_SOURCE_PATH = os.path.join(APPS_DIR, "smart_vent_controller.py")

# Same rationale as the other nudge suites: the mechanism's production master
# switch is orthogonal to whether its state machine is correct, so force it on
# for this offline run.
svc.SETPOINT_NUDGE_ENABLED = True
# NOTE: the comfort (worst_excess) source is deliberately LEFT at the production default (False).

APP_DIR = tempfile.mkdtemp(prefix="precool_nudge_test_")

# Inside the overnight window (01:00-06:30) on 2026-09-03.
IN_WINDOW = datetime(2026, 9, 3, 1, 5, 0)
# Broad daylight, unambiguously outside the window.
OUT_WINDOW = datetime(2026, 9, 3, 13, 0, 0)


# ---- fake HA backend ---------------------------------------------------------
class FakeHA(svc.SmartVentController):
    """Full instance-state stub. The init list is copied wholesale from
    test_precool_foundation.py + test_nudge_state_persistence.py (the known
    AttributeError gotcha on this file: a partial stub blows up deep inside a
    pass that never mentions the missing field).
    """
    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=72.0, sp_heat=64.0, clock=None, tmp=None):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = clock or IN_WINDOW
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
        # Pre-cool state (phase 1 fields + the phase 2 suppression flag).
        self._precool_min_temps = {}
        self._precool_window_id = None
        self._precool_dewpoint_unavailable_logged = False
        self._precool_humidity_blocked_logged = False
        self._precool_suppressed_window_id = None
        # Persistence wiring.
        self._nudge_persist_disable = False
        self._nudge_restore_pending = False
        self._nudge_state_file = os.path.join(tmp or APP_DIR,
                                              svc.NUDGE_STATE_FILENAME)
        self.sp_calls = []
        self.logs = []
        self._mode = mode
        self._hvac_mode = hvac_mode
        self._hvac_action = hvac_action
        self._sp_cool = sp_cool
        self._sp_heat = sp_heat
        # Every room neutral at 68.0 and UNOCCUPIED. 68.0 against a cool
        # setpoint of 72.0 keeps every passive room's off_target negative, so
        # comfort's worst_excess stays 0.0 unless a test deliberately heats a
        # room -- including Hallway/Kitchen, which have no occupancy sensor and
        # therefore always count as occupied.
        for _zn, zone in svc.ZONES.items():
            for _rn, s in zone["rooms"].items():
                self.states[s["temp"]] = 68.0
                if s.get("occupancy"):
                    self.states[s["occupancy"]] = "off"
                for v in s.get("vents", []):
                    self.attrs[(v, "current_tilt_position")] = 100
        # Humidity conditions that PASS the gate, so window tests aren't
        # accidentally blocked by the humidity guard.
        self.states[svc.PRECOOL_DEWPOINT_ENTITY] = 50.0
        self.states[svc.PRECOOL_HUMIDITY_ENTITY] = 50.0
        self._set_thermostat()

    # ---- time ---------------------------------------------------------------
    def datetime(self, aware=False):
        return self._clock

    def advance(self, seconds):
        self._clock += timedelta(seconds=seconds)

    # ---- HA primitives ------------------------------------------------------
    def get_state(self, entity, attribute=None):
        if attribute:
            return self.attrs.get((entity, attribute))
        return self.states.get(entity)

    def set_state(self, entity, state=None, attributes=None):
        self.published[entity] = (state, attributes or {})

    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def call_service(self, service, **kwargs):
        self.sp_calls.append((service, kwargs))

    # ---- helpers ------------------------------------------------------------
    def _set_thermostat(self):
        self.attrs[(svc.THERMOSTAT, "all")] = {
            "state": self._hvac_mode,
            "attributes": {
                "hvac_mode": self._hvac_mode,
                "hvac_action": self._hvac_action,
                "target_temp_high": self._sp_cool,
                "target_temp_low": self._sp_heat,
                "current_temperature": 72.0,
            },
        }
        self.states[svc.SETPOINT_TRUTH_COOL] = self._sp_cool
        self.states[svc.SETPOINT_TRUTH_HEAT] = self._sp_heat

    def live_cool(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"]

    def set_cloud_truth(self, cool=None, heat=None):
        if cool is not None:
            self.states[svc.SETPOINT_TRUTH_COOL] = cool
        if heat is not None:
            self.states[svc.SETPOINT_TRUTH_HEAT] = heat

    def set_live_setpoints(self, cool=None, heat=None):
        a = self.attrs[(svc.THERMOSTAT, "all")]["attributes"]
        if cool is not None:
            a["target_temp_high"] = float(cool)
        if heat is not None:
            a["target_temp_low"] = float(heat)
        self.set_cloud_truth(cool=cool, heat=heat)

    def echo_our_command(self):
        """Simulate the ecobee echoing back exactly what we commanded."""
        self.set_live_setpoints(cool=self._sp_commanded_cool,
                                heat=self._sp_commanded_heat)

    def set_room_temp(self, zone, room, temp):
        self.states[svc.ZONES[zone]["rooms"][room]["temp"]] = float(temp)

    def occupy(self, zone, room):
        self.states[svc.ZONES[zone]["rooms"][room]["occupancy"]] = "on"

    def set_hvac_action(self, action):
        self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["hvac_action"] = action
        self._hvac_action = action

    def run_cycle(self, with_precool=True):
        """One control-loop-shaped nudge cycle: compute the pre-cool gate ONCE
        (exactly as control_loop does) and hand that same gate to the nudge."""
        gate = self._precool_gate() if with_precool else None
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat,
                                          self._mode, precool_gate=gate)


GAME = ("upstairs", "Game Room")
GB1 = ("upstairs", "Guest Bedroom 1")


def set_precool_temps(ha, game, gb1):
    ha.set_room_temp(*GAME, game)
    ha.set_room_temp(*GB1, gb1)


def active_gate(ha):
    return ha._precool_gate()


def holds(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/set_hold_temperature"]


def resumes(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/resume_top_event"]


PASS = []
def check(label, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + label)


with open(SVC_SOURCE_PATH) as f:
    _source = f.read()



# =============================================================================
# 1. Production default
# =============================================================================
import re
check("T1 SETPOINT_NUDGE_COMFORT_ENABLED is False in the controller source (production default)",
      re.search(r"^SETPOINT_NUDGE_COMFORT_ENABLED\s*=\s*False\b", _source, re.M) is not None)
check("T1 master switch SETPOINT_NUDGE_ENABLED is still True (pre-cool needs the state machine)",
      svc.SETPOINT_NUDGE_ENABLED is True)
check("T1 this suite really runs with the comfort source off",
      svc.SETPOINT_NUDGE_COMFORT_ENABLED is False)

# =============================================================================
# 2. A hot OCCUPIED room alone no longer moves the setpoint (cooling)
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=OUT_WINDOW)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 80.0)   # far past setpoint + margin: big comfort excess
for _ in range(3):
    ha.run_cycle(with_precool=False)
check("T2 hot occupied Game Room (80F vs 72F cool sp), pre-cool off: ZERO holds written",
      len(holds(ha)) == 0)
check("T2 ... and the nudge never takes ownership", ha._sp_owned is False)
ha2 = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=OUT_WINDOW)
ha2.occupy("upstairs", "Game Room")
ha2.set_room_temp("upstairs", "Game Room", 80.0)
ha2.run_cycle(with_precool=True)   # gate computed, but it is daytime -> inactive
check("T2 same with the pre-cool gate handed in (inactive outside the window): zero holds",
      len(holds(ha2)) == 0 and ha2._sp_owned is False)

# =============================================================================
# 3. ... and for a cold occupied room in HEATING
# =============================================================================
ha = FakeHA(hvac_action="heating", sp_cool=75.0, sp_heat=70.0, clock=OUT_WINDOW)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 58.0)   # far below the heat setpoint
for _ in range(3):
    ha.run_cycle(with_precool=False)
check("T3 cold occupied room while heating: ZERO holds written, nudge not owned",
      len(holds(ha)) == 0 and ha._sp_owned is False)

# =============================================================================
# 4. Pre-cool demand still engages (the overnight AC pre-cool is a separate feature)
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha, 71.0, 69.0)   # pre-cool demand 3.0
ha.run_cycle()
check("T4 pre-cool demand alone still ENGAGES the nudge inside the window", ha._sp_owned is True and len(holds(ha)) == 1)
check("T4 commanded cool == baseline 72.0 - 2.0 == 70.0", ha._sp_commanded_cool == 70.0)

# comfort excess present at the same time must not add anything to pre-cool's depth
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
ha.occupy("upstairs", "Guest Bedroom 2")
ha.set_room_temp("upstairs", "Guest Bedroom 2", 72.0 + svc.PRIORITY_MARGIN_BASE + 1.6)
set_precool_temps(ha, 71.0, 69.0)
ha.run_cycle()
check("T4 pre-cool + a hot occupied room: still exactly one hold, still 70.0",
      len(holds(ha)) == 1 and ha._sp_commanded_cool == 70.0)

# =============================================================================
# 5. Pre-cool released when satisfied (comfort source off does not strand the hold)
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha, 71.0, 69.0)
ha.run_cycle()
assert ha._sp_owned is True
ha.echo_our_command()
set_precool_temps(ha, 60.0, 60.0)   # both rooms below their floors: pre-cool satisfied
ha.advance_clock = None
ha._clock = IN_WINDOW.replace(minute=40)
ha.run_cycle()
check("T5 once pre-cool is satisfied the hold is released (resume_top_event) and ownership cleared",
      len(resumes(ha)) >= 1 and ha._sp_owned is False)

# =============================================================================
# 6. A comfort-owned hold that survives a restart (flag flipped off while owned)
# =============================================================================
def owned_comfort_hold(hvac_action, sp_cool, sp_heat, room_temp, clock):
    """Engage a hold through the comfort source (flag True), echo it back, then flip the flag
    to its production value (False), as a restart onto the new code would."""
    svc.SETPOINT_NUDGE_COMFORT_ENABLED = True
    ha = FakeHA(hvac_action=hvac_action, sp_cool=sp_cool, sp_heat=sp_heat, clock=clock)
    ha.occupy("upstairs", "Game Room")
    ha.set_room_temp("upstairs", "Game Room", room_temp)
    ha.run_cycle(with_precool=False)
    assert ha._sp_owned is True and len(holds(ha)) == 1, "setup: comfort hold did not engage"
    ha.echo_our_command()
    svc.SETPOINT_NUDGE_COMFORT_ENABLED = False
    return ha

ha = owned_comfort_hold("cooling", 72.0, 64.0, 80.0, OUT_WINDOW)
ha._clock = OUT_WINDOW.replace(minute=30)
ha.run_cycle(with_precool=True)
check("T6 leftover COOLING comfort hold (daytime) is released on the first cycle after the flag is off",
      len(resumes(ha)) == 1 and ha._sp_owned is False)

ha = owned_comfort_hold("heating", 75.0, 70.0, 58.0, OUT_WINDOW)
ha._clock = OUT_WINDOW.replace(minute=30)
ha.run_cycle(with_precool=True)
check("T6 leftover HEATING comfort hold is released on the first cycle after the flag is off",
      len(resumes(ha)) == 1 and ha._sp_owned is False)

# In the pre-cool window with pre-cool demand still unsatisfied the leftover hold is HELD
# (it becomes a pre-cool hold at the same 2F depth) rather than released and re-engaged.
svc.SETPOINT_NUDGE_COMFORT_ENABLED = True
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 80.0)
set_precool_temps(ha, 71.0, 69.0)
ha.set_room_temp("upstairs", "Game Room", 80.0)
ha.run_cycle()
assert ha._sp_owned is True
ha.echo_our_command()
svc.SETPOINT_NUDGE_COMFORT_ENABLED = False
ha._clock = IN_WINDOW.replace(minute=30)
ha.run_cycle()
check("T6 in-window with pre-cool still unsatisfied: leftover hold is HELD (no release, no extra write)",
      len(resumes(ha)) == 0 and ha._sp_owned is True and len(holds(ha)) == 1)

# =============================================================================
# 7. Diagnostic: the suppressed comfort demand is logged once on change, not every cycle
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=OUT_WINDOW)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 80.0)
for _ in range(4):
    ha.run_cycle(with_precool=False)
n_logged = sum(1 for m in ha.logs if "comfort source OFF" in m)
check("T7 suppressed comfort demand logged exactly once across 4 hot cycles", n_logged == 1)
ha.set_room_temp("upstairs", "Game Room", 68.0)
ha.run_cycle(with_precool=False)
check("T7 and once more when the room is back in range ('no longer')",
      sum(1 for m in ha.logs if "comfort source OFF" in m) == 2)

print()
print("ALL PASS" if all(PASS) else "SOME FAILED", f"({sum(PASS)}/{len(PASS)})")
sys.exit(0 if all(PASS) else 1)
