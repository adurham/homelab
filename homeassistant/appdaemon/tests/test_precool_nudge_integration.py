"""Overnight pre-cool PHASE 2: pre-cool as a SECOND DEMAND SOURCE for the
EXISTING setpoint nudge (added 2026-09-02).

Phase 1 (tests/test_precool_foundation.py) built the window/targets/abort/
humidity/tracker/vent-pass machinery and deliberately did NOT touch setpoints.
This suite covers the phase that wires pre-cool into the nudge -- WITHOUT
adding a second setpoint writer:

  - _precool_demand(): pre-cool's own excess, measured from the FLOORS.
    POSITIVE == still above the floor == still wants cooling. MAX across the
    two target rooms, floored at 0.0, occupancy-independent, 0.0 whenever the
    gate is inactive.
  - MAX (never SUM) combination with comfort's worst_excess, feeding the ONE
    existing pure _commanded_setpoints() depth computation, still bounded by
    the SHARED SETPOINT_NUDGE_MAX_F = 2.0 total cap.
  - The extended RELEASE gate: inside the pre-cool window, release requires
    BOTH comfort AND pre-cool satisfied. This is the no-chatter requirement --
    releasing on comfort alone while pre-cool still wants engagement makes the
    nudge pop and re-engage every single cycle, all night.
  - Human-override suppression for the REST of that night's window (NOT merely
    the 120-minute cooldown), persisted across a restart.
  - Byte-identical behavior whenever pre-cool is not running.

No pytest / appdaemon needed: same stub pattern as the other suites.
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

APPS_DIR = os.environ.get(
    "SVC_APPS_DIR",
    "/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps")
sys.path.insert(0, APPS_DIR)
import smart_vent_controller as svc  # noqa: E402

SVC_SOURCE_PATH = os.path.join(APPS_DIR, "smart_vent_controller.py")

# Same rationale as the other nudge suites: the mechanism's production master
# switch is orthogonal to whether its state machine is correct, so force it on
# for this offline run.
svc.SETPOINT_NUDGE_ENABLED = True

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
        for zn, zone in svc.ZONES.items():
            for rn, s in zone["rooms"].items():
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
# 1. _precool_demand(): floor-relative, MAX across rooms, never negative
# =============================================================================
ha = FakeHA()
set_precool_temps(ha, 71.0, 69.5)   # 71-68 = 3.0 ; 69.5-69 = 0.5
g = active_gate(ha)
check("T1 gate is active inside the window (precondition)", g.active is True)
check("T1 Game Room 71.0 (floor 68) + GB1 69.5 (floor 69) -> demand == 3.0",
      ha._precool_demand(g) == 3.0)

ha = FakeHA()
set_precool_temps(ha, 68.0, 69.0)   # both exactly AT their floors
check("T1 both rooms exactly at their floors -> demand == 0.0",
      ha._precool_demand(active_gate(ha)) == 0.0)

ha = FakeHA()
set_precool_temps(ha, 66.0, 67.0)   # both BELOW their floors
d = ha._precool_demand(active_gate(ha))
check("T1 both rooms below their floors -> demand == 0.0, never negative",
      d == 0.0)

# Sign convention, explicitly: ABOVE the floor is POSITIVE (wants cooling).
ha = FakeHA()
set_precool_temps(ha, 60.0, 72.0)   # only GB1 is above its floor: 72-69 = 3.0
check("T1 only GB1 above its floor -> demand == 3.0 (a room that BEAT its "
      "floor cannot cancel the other room's demand)",
      ha._precool_demand(active_gate(ha)) == 3.0)

# Unreadable temps are SKIPPED, not treated as zero-or-infinite demand.
ha = FakeHA()
set_precool_temps(ha, 71.0, 69.5)
ha.states[svc.ZONES["upstairs"]["rooms"]["Game Room"]["temp"]] = "unavailable"
check("T1 unreadable Game Room is skipped -> demand falls back to GB1's 0.5",
      ha._precool_demand(active_gate(ha)) == 0.5)

# Occupancy does NOT gate pre-cool demand (a sleeping person may not trip PIR).
ha = FakeHA()
set_precool_temps(ha, 71.0, 69.0)
check("T1 demand is computed with BOTH target rooms UNOCCUPIED (occupancy "
      "does not gate pre-cool)",
      ha._precool_demand(active_gate(ha)) == 3.0)


# =============================================================================
# 2. Pre-cool demand ALONE engages the nudge (comfort worst_excess == 0.0)
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha, 71.0, 69.0)   # precool demand 3.0; both under cool sp 72
ha.run_cycle()
check("T2 pre-cool demand alone ENGAGES the nudge inside the window",
      ha._sp_owned is True and len(holds(ha)) == 1)
check("T2 engage was NOT driven by comfort (no room is over the setpoint)",
      all(ha.states[s["temp"]] <= 72.0
          for _zn, z in svc.ZONES.items() for _rn, s in z["rooms"].items()))
check("T2 commanded cool == baseline 72.0 - 2.0 == 70.0",
      ha._sp_commanded_cool == 70.0)
check("T2 exactly one setHold, zero resumes", len(resumes(ha)) == 0)

# Same conditions but the gate is NOT handed in -> pre-PHASE-2 behavior: no
# engage at all. This is the byte-identical-when-not-running guarantee.
ha_off = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha_off, 71.0, 69.0)
ha_off.run_cycle(with_precool=False)
check("T2 identical scenario WITHOUT the pre-cool gate -> no engage "
      "(pre-cool is the only reason T2 engaged)",
      ha_off._sp_owned is False and len(holds(ha_off)) == 0)


# =============================================================================
# 3. Depth is MAX, not SUM -- the 2.0F cap is SHARED
# =============================================================================
# Comfort 1.6 (occupied GB2 at 72 + margin 1.5 + 1.6) AND pre-cool 3.0.
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
ha.occupy("upstairs", "Guest Bedroom 2")
ha.set_room_temp("upstairs", "Guest Bedroom 2",
                 72.0 + svc.PRIORITY_MARGIN_BASE + 1.6)
set_precool_temps(ha, 71.0, 69.0)   # pre-cool demand 3.0
g = active_gate(ha)
check("T3 precondition: pre-cool demand is 3.0", ha._precool_demand(g) == 3.0)
ha.run_cycle()
check("T3 engaged", ha._sp_owned is True and len(holds(ha)) == 1)
check("T3 commanded cool == baseline - 2.0 (72.0 -> 70.0), NOT deeper",
      ha._sp_commanded_cool == 70.0)
movement = 72.0 - ha._sp_commanded_cool
check("T3 total movement 2.0F never exceeds SETPOINT_NUDGE_MAX_F",
      movement <= svc.SETPOINT_NUDGE_MAX_F + 1e-9
      and abs(movement - 2.0) < 1e-9)
check("T3 the SUM (1.6 + 3.0 = 4.6F) would have moved further -- it did not",
      movement < 4.6)
check("T3 commanded setpoint is a WHOLE degree (ecobee quantization)",
      float(ha._sp_commanded_cool).is_integer()
      and float(ha._sp_commanded_heat).is_integer())

# The combination itself, asserted directly on the ONE pure depth function:
# feeding max(1.6, 3.0) and feeding the sum must not differ, because both
# saturate the shared cap -- and neither may exceed it.
c_max, h_max = ha._commanded_setpoints(72.0, 64.0, False, max(1.6, 3.0), True)
c_sum, h_sum = ha._commanded_setpoints(72.0, 64.0, False, 1.6 + 3.0, True)
check("T3 _commanded_setpoints saturates at the shared 2.0F cap either way "
      "(no additional pre-cool allowance exists)",
      c_max == 70.0 and c_sum == 70.0)
check("T3 SETPOINT_NUDGE_MAX_F is still exactly 2.0 (not widened)",
      svc.SETPOINT_NUDGE_MAX_F == 2.0)

# MAX-vs-SUM, observed where the two actually DIFFER. Above, both saturate the
# shared cap, so the commanded value alone cannot distinguish them: GAIN(2.0) *
# ENGAGE_F(1.5) = 3.0 >= MAX_F(2.0), so ANY excess large enough to engage at
# all already saturates. The one place the combination rule is observable is
# therefore the ENGAGE BOUNDARY: comfort 0.8 and pre-cool 0.8 give
# max == 0.8 (below ENGAGE_F -> must NOT engage) but
# sum == 1.6 (above ENGAGE_F -> would wrongly engage).
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
ha.occupy("upstairs", "Guest Bedroom 2")
ha.set_room_temp("upstairs", "Guest Bedroom 2",
                 72.0 + svc.PRIORITY_MARGIN_BASE + 0.8)   # comfort excess 0.8
set_precool_temps(ha, 68.8, 69.0)                          # pre-cool demand 0.8
g = active_gate(ha)
check("T3 boundary precondition: pre-cool demand is 0.8",
      abs(ha._precool_demand(g) - 0.8) < 1e-9)
check("T3 boundary precondition: each source alone is below "
      "SETPOINT_NUDGE_ENGAGE_F, but their SUM (1.6) is above it",
      0.8 < svc.SETPOINT_NUDGE_ENGAGE_F < 1.6)
ha.run_cycle()
check("T3 MAX not SUM: comfort 0.8 + pre-cool 0.8 does NOT engage "
      "(max(0.8, 0.8) = 0.8 < engage 1.5; the SUM 1.6 would have engaged)",
      ha._sp_owned is False and len(holds(ha)) == 0)


# =============================================================================
# 4. NO-CHATTER: comfort satisfied but pre-cool still wants it -> NO release,
#    and no release-then-re-engage across consecutive cycles.
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha, 71.0, 69.0)   # pre-cool demand 3.0, comfort 0.0
ha.run_cycle()                       # cycle 1: engage on pre-cool alone
check("T4 cycle 1: engaged", ha._sp_owned is True and len(holds(ha)) == 1)
ha.echo_our_command()                # ecobee echoes our hold back
ha.advance(120)
ha.run_cycle()                       # cycle 2: comfort 0.0, pre-cool 3.0
check("T4 cycle 2: did NOT release while pre-cool demand is still 3.0",
      ha._sp_owned is True and len(resumes(ha)) == 0)
ha.advance(120)
ha.run_cycle()                       # cycle 3: still held
check("T4 cycle 3: ownership held CONTINUOUSLY -- exactly 1 engage, 0 releases",
      ha._sp_owned is True
      and len(holds(ha)) == 1
      and len(resumes(ha)) == 0)
check("T4 the hold is explained in the log (held for pre-cool demand)",
      any("HELD for pre-cool demand" in m for m in ha.logs))

# CONTROL GROUP -- this is what proves comfort really was satisfied on those
# held cycles. Identical scenario, identical cycle sequence, but WITHOUT the
# pre-cool gate handed in (i.e. pre-PHASE-2 behavior). Comfort alone releases
# on cycle 2 -- so pre-cool's demand is the ONLY thing that held it above.
ctl = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ctl, 71.0, 69.0)
# Give it a comfort reason to engage in the first place (pre-cool can't, with
# no gate), then satisfy comfort while the pre-cool floors stay unmet.
ctl.occupy("upstairs", "Guest Bedroom 2")
ctl.set_room_temp("upstairs", "Guest Bedroom 2",
                  72.0 + svc.PRIORITY_MARGIN_BASE + 2.0)
ctl.run_cycle(with_precool=False)
ctl.echo_our_command()
ctl.advance(120)
ctl.set_room_temp("upstairs", "Guest Bedroom 2", 68.0)   # comfort satisfied
ctl.run_cycle(with_precool=False)
check("T4 CONTROL: same rooms/temps WITHOUT the pre-cool gate release on "
      "comfort alone -- proving comfort was satisfied and pre-cool's demand "
      "is the only thing that held the nudge in the test above",
      ctl._sp_owned is False and len(resumes(ctl)) == 1
      and ctl._precool_demand(ctl._precool_gate()) == 3.0)


# =============================================================================
# 5. Release DOES happen inside the window once BOTH are satisfied
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW)
set_precool_temps(ha, 71.0, 69.0)
ha.run_cycle()                       # engage on pre-cool
check("T5 precondition: engaged", ha._sp_owned is True)
ha.echo_our_command()
ha.advance(120)
# Both rooms now within PRECOOL_NUDGE_RELEASE_F of their floors; comfort is
# already satisfied (every room is below the live cool setpoint).
set_precool_temps(ha, 68.4, 69.0)    # demand 0.4 <= 0.5
g = active_gate(ha)
check("T5 pre-cool demand now 0.4 <= PRECOOL_NUDGE_RELEASE_F",
      abs(ha._precool_demand(g) - 0.4) < 1e-9
      and ha._precool_demand(g) <= svc.PRECOOL_NUDGE_RELEASE_F)
ha.run_cycle()
check("T5 released once BOTH comfort and pre-cool are satisfied",
      ha._sp_owned is False and len(resumes(ha)) == 1)
check("T5 PRECOOL_NUDGE_RELEASE_F exists as its own explicit constant",
      hasattr(svc, "PRECOOL_NUDGE_RELEASE_F"))


# =============================================================================
# 6. OUTSIDE the window, release behavior is exactly today's: comfort <= 0.5
#    releases immediately REGARDLESS of room temps vs the pre-cool floors.
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=OUT_WINDOW)
ha.occupy("upstairs", "Guest Bedroom 2")
ha.set_room_temp("upstairs", "Guest Bedroom 2",
                 72.0 + svc.PRIORITY_MARGIN_BASE + 2.0)   # comfort excess 2.0
set_precool_temps(ha, 76.0, 76.0)    # WAY above both floors
ha.run_cycle()
check("T6 engaged on comfort outside the window", ha._sp_owned is True)
g = active_gate(ha)
check("T6 gate inactive outside the window and demand is exactly 0.0",
      g.active is False and ha._precool_demand(g) == 0.0)
ha.echo_our_command()
ha.advance(120)
ha.set_room_temp("upstairs", "Guest Bedroom 2", 68.0)     # comfort satisfied
# Rooms are STILL far above their pre-cool floors -- must not matter at all.
ha.run_cycle()
check("T6 comfort satisfied -> released IMMEDIATELY even though both target "
      "rooms are 8F above their floors",
      ha._sp_owned is False and len(resumes(ha)) == 1)


# =============================================================================
# 7. Human override inside the window suppresses pre-cool for the WHOLE night
# =============================================================================
tmp7 = tempfile.mkdtemp()
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW, tmp=tmp7)
set_precool_temps(ha, 71.0, 69.0)
ha.run_cycle()                                    # engage on pre-cool
check("T7 precondition: engaged inside the window", ha._sp_owned is True)
# The human moves the setpoint out from under us.
ha.set_live_setpoints(cool=74.0, heat=64.0)
ha.run_cycle()                                    # fresh mismatch -> wait
check("T7 fresh mismatch is NOT yet believed (still owned, not suppressed)",
      ha._sp_owned is True
      and ha._precool_suppressed_window_id is None)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_cycle()                                    # confirmed override
check("T7 confirmed override relinquished ownership",
      ha._sp_owned is False)
check("T7 pre-cool suppressed for THIS window-night",
      ha._precool_suppressed_window_id
      == ha._precool_window_id_for(ha.datetime()))
g = active_gate(ha)
check("T7 gate now inactive with reason=suppressed, demand exactly 0.0",
      g.active is False and g.suppressed is True
      and ha._precool_demand(g) == 0.0)
check("T7 the comfort cooldown was set too (comfort behavior unchanged)",
      ha._sp_override_cooldown_until is not None)

# Advance PAST the 120-minute cooldown while STILL INSIDE the same window.
ha.advance(svc.SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN * 60 + 60)
check("T7 clock is still inside the SAME window-night",
      ha._precool_window_active(ha.datetime()) is True
      and ha._precool_window_id_for(ha.datetime()) == "2026-09-03")
check("T7 the comfort cooldown has numerically EXPIRED",
      ha.datetime() >= ha._sp_override_cooldown_until)
g = active_gate(ha)
check("T7 pre-cool STILL suppressed after the cooldown expired (same window)",
      g.active is False and g.suppressed is True
      and ha._precool_demand(g) == 0.0)
set_precool_temps(ha, 71.0, 69.0)     # rooms still want pre-cool
holds_before = len(holds(ha))
ha.run_cycle()
check("T7 pre-cool does NOT re-engage the nudge in the vetoed window",
      ha._sp_owned is False and len(holds(ha)) == holds_before)

# Move to the NEXT night's window -> pre-cool is allowed again.
ha._clock = datetime(2026, 9, 4, 1, 5, 0)
set_precool_temps(ha, 71.0, 69.0)
g = active_gate(ha)
check("T7 NEXT night: pre-cool allowed again (stale veto id is inert)",
      g.active is True and g.suppressed is False
      and ha._precool_demand(g) == 3.0)
ha.run_cycle()
check("T7 NEXT night: pre-cool engages the nudge again",
      ha._sp_owned is True and len(holds(ha)) == holds_before + 1)

# An override OUTSIDE the window must not veto anything (no-op).
ha2 = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=OUT_WINDOW, tmp=tmp7)
ha2.occupy("upstairs", "Guest Bedroom 2")
ha2.set_room_temp("upstairs", "Guest Bedroom 2",
                  72.0 + svc.PRIORITY_MARGIN_BASE + 2.0)
ha2.run_cycle()
ha2.set_live_setpoints(cool=74.0, heat=64.0)
ha2.run_cycle()
ha2.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha2.run_cycle()
check("T7 daytime override relinquished (comfort path unchanged)",
      ha2._sp_owned is False and ha2._sp_override_cooldown_until is not None)
check("T7 daytime override does NOT veto tonight's pre-cool window",
      ha2._precool_suppressed_window_id is None)


# =============================================================================
# 8. Restart persistence (NUDGE_STATE_VERSION stays 1; old files still load)
# =============================================================================
tmp8 = tempfile.mkdtemp()
ha = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=IN_WINDOW, tmp=tmp8)
set_precool_temps(ha, 71.0, 69.0)
ha.run_cycle()
ha.set_live_setpoints(cool=74.0, heat=64.0)
ha.run_cycle()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_cycle()                       # confirmed override -> suppress + persist
check("T8 precondition: suppression active and persisted",
      ha._precool_suppressed_window_id == "2026-09-03")
with open(ha._nudge_state_file) as f:
    rec = json.load(f)
check("T8 state file records the suppressed window id",
      rec.get("precool_suppressed_window_id") == "2026-09-03")
check("T8 state file version is still 1",
      rec.get("version") == 1 and svc.NUDGE_STATE_VERSION == 1)

# 'Restart': a brand-new instance reading the same state file.
ha_restart = FakeHA(sp_cool=74.0, sp_heat=64.0, clock=ha.datetime(), tmp=tmp8)
ha_restart._restore_nudge_ownership()
check("T8 restart: suppression survived",
      ha_restart._precool_suppressed_window_id == "2026-09-03")
set_precool_temps(ha_restart, 71.0, 69.0)
g = active_gate(ha_restart)
check("T8 restart: pre-cool still vetoed after restore (gate inactive, "
      "demand 0.0)",
      g.active is False and g.suppressed is True
      and ha_restart._precool_demand(g) == 0.0)
ha_restart.run_cycle()
check("T8 restart: a restarted app does NOT resurrect the vetoed pre-cool",
      len(holds(ha_restart)) == 0)

# The min-temp tracker round-trips through JSON (tuple keys -> triples).
check("T8 min-temp tracker persisted as [zone, room, temp] triples",
      isinstance(rec.get("precool_min_temps"), list)
      and all(len(e) == 3 for e in rec["precool_min_temps"]))
check("T8 min-temp tracker restored with TUPLE keys intact",
      all(isinstance(k, tuple) and len(k) == 2
          for k in ha_restart._precool_min_temps)
      and ha_restart._precool_min_temps == ha._precool_min_temps)

# OLD-FORMAT file: version 1, but NONE of the phase-2 keys. Must restore
# without raising, and the control loop must still run.
tmp8b = tempfile.mkdtemp()
old_record = {
    "version": 1,
    "owned": True,
    "commanded_at": IN_WINDOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "commanded_cool": 70.0,
    "commanded_heat": 64.0,
    "baseline_cool": 72.0,
    "baseline_heat": 64.0,
    "heating": False,
    "override_cooldown_until": None,
}
with open(os.path.join(tmp8b, svc.NUDGE_STATE_FILENAME), "w") as f:
    f.write(json.dumps(old_record))
ha_old = FakeHA(sp_cool=70.0, sp_heat=64.0, clock=IN_WINDOW, tmp=tmp8b)
_raised = None
try:
    ha_old._restore_nudge_ownership()
except Exception as e:  # noqa: BLE001 - the assertion IS "must not raise"
    _raised = e
check("T8 OLD-format file (no phase-2 keys) restores WITHOUT raising",
      _raised is None)
check("T8 OLD-format file still restores the pre-phase-2 ownership record",
      ha_old._sp_owned is True and ha_old._sp_baseline_cool == 72.0)
check("T8 OLD-format file leaves pre-cool state at safe defaults",
      ha_old._precool_suppressed_window_id is None)
# ...and the control loop path still runs against it.
set_precool_temps(ha_old, 71.0, 69.0)
_raised2 = None
try:
    ha_old.run_cycle()
except Exception as e:  # noqa: BLE001
    _raised2 = e
check("T8 OLD-format file does not crash the control loop", _raised2 is None)


# =============================================================================
# 9/10. Structural invariants: version pinned, still exactly ONE setpoint writer
# =============================================================================
check("T9 NUDGE_STATE_VERSION is still exactly 1",
      svc.NUDGE_STATE_VERSION == 1)

_call_sites = re.findall(r'self\._write_setpoint_nudge\(', _source)
check("T10 exactly 2 call sites of _write_setpoint_nudge in the whole file "
      "(no second setpoint writer was added)",
      len(_call_sites) == 2)
_precool_block = _source[_source.index("def _precool_window_active"):
                         _source.index("def _write_setpoint_nudge")]
check("T10 no _precool_* helper calls _write_setpoint_nudge",
      "_write_setpoint_nudge(" not in _precool_block)
check("T10 no _precool_* helper calls set_hold_temperature",
      "set_hold_temperature" not in _precool_block)
# _apply_backpressure_rooms must remain the absolute last pass, untouched.
check("T10 _apply_backpressure_rooms still runs AFTER the setpoint nudge in "
      "control_loop",
      _source.index("self._apply_setpoint_nudge(")
      < _source.index("self._apply_backpressure_rooms("))


# =============================================================================
# 11. Gate INACTIVE (window / cold-abort / humidity) -> demand exactly 0.0 and
#     the nudge behaves exactly as it does today.
# =============================================================================
# (a) outside the window
ha = FakeHA(clock=OUT_WINDOW)
set_precool_temps(ha, 76.0, 76.0)
g = active_gate(ha)
check("T11a outside the window -> demand 0.0",
      g.active is False and ha._precool_demand(g) == 0.0)

# (b) cold-abort: an OCCUPIED room house-wide at/below PRECOOL_ABORT_OCCUPIED_F
ha = FakeHA(clock=IN_WINDOW)
set_precool_temps(ha, 76.0, 76.0)
ha.occupy("downstairs", "Living Room")
ha.set_room_temp("downstairs", "Living Room", 66.5)
g = active_gate(ha)
check("T11b cold-abort -> demand 0.0 despite targets 8F above their floors",
      g.active is False and g.cold_abort is True
      and ha._precool_demand(g) == 0.0)

# (c) humidity-blocked
ha = FakeHA(clock=IN_WINDOW)
set_precool_temps(ha, 76.0, 76.0)
ha.states[svc.PRECOOL_DEWPOINT_ENTITY] = 60.0   # > PRECOOL_DEWPOINT_MAX_F
g = active_gate(ha)
check("T11c humidity-blocked -> demand 0.0",
      g.active is False and g.humidity_ok is False
      and ha._precool_demand(g) == 0.0)

# (d) with the gate inactive, the nudge is byte-identical to today: an engage
#     driven purely by comfort produces the same command with and without a
#     pre-cool gate handed in, and a comfort-satisfied cycle releases.
def comfort_only(clock, with_precool):
    h = FakeHA(sp_cool=72.0, sp_heat=64.0, clock=clock)
    h.occupy("upstairs", "Guest Bedroom 2")
    h.set_room_temp("upstairs", "Guest Bedroom 2",
                    72.0 + svc.PRIORITY_MARGIN_BASE + 2.0)
    set_precool_temps(h, 76.0, 76.0)   # irrelevant: gate is inactive at OUT
    h.run_cycle(with_precool=with_precool)
    return h

h_with = comfort_only(OUT_WINDOW, True)
h_without = comfort_only(OUT_WINDOW, False)
check("T11d gate inactive: identical commanded setpoints with and without a "
      "pre-cool gate",
      h_with._sp_commanded_cool == h_without._sp_commanded_cool
      and h_with._sp_commanded_heat == h_without._sp_commanded_heat)
check("T11d gate inactive: identical service-call counts",
      len(holds(h_with)) == len(holds(h_without)) == 1)
for h in (h_with, h_without):
    h.echo_our_command()
    h.advance(120)
    h.set_room_temp("upstairs", "Guest Bedroom 2", 68.0)
    h.run_cycle(with_precool=(h is h_with))
check("T11d gate inactive: BOTH release identically on comfort alone",
      h_with._sp_owned is False and h_without._sp_owned is False
      and len(resumes(h_with)) == len(resumes(h_without)) == 1)


# =============================================================================
print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
