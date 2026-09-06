"""Offline RED-GREEN regression for the setpoint-nudge RELEASE reference frame.

THE BUG (root-caused from 7-day production data, 2026-08-30 -> 2026-09-06, and
verified in code + live entity state + AppDaemon logs on 2026-09-06): the nudge
held the house cool setpoint at 70F (baseline 72F) for 15-20+ HOURS on most
days instead of acting as a rare intervention. It only ever cleared at the
ecobee's own midnight/7am schedule transitions (which pop the nextTransition
hold) and re-engaged within 1-2 hours — while the chronic hot rooms it was
supposed to help (Game Room avg 74.3F, Half Bathroom avg 74.1F, never below
72.3F all week) still overheated, and comfort rooms got dragged to 65-66F.

MECHANISM: `_apply_setpoint_nudge` computed the worst_excess that drives BOTH
the engage AND the release gate via `_off_target` -> `_current_setpoint` ->
the LIVE thermostat setpoint (climate.ecobee_thermostat target_temp_high).
During our own hold, that LIVE setpoint IS our nudged value (70), not the
user's baseline (72) — live-verified 2026-09-06: desired_cool sensor and the
climate entity's target_temp_high both read 70 while the scheduled baseline
is 72, and the AppDaemon log shows the nudge computing e.g. "comfort
satisfied (worst_excess 0.49F)" for rooms sitting ~0.5F over the NUDGED 70.

So the nudge demanded, to release, that the worst occupied room come within
margin+0.5F of a setpoint 2F BELOW the user's own baseline — arithmetically
unreachable for rooms that can't get under ~72.3F. A nudge that engages at
excess-vs-baseline 2.4 (room 75.9 vs 72) then measures its own release
condition against 70 can never see the recovery it is waiting for. The hold
lived until the schedule killed it. (The old docstring in
test_nudge_baseline_scoring.py claimed the LIVE reference was deliberate —
"feeding it the baseline would break its release logic so it would never
release" — which is exactly backwards: the baseline is the ONLY reference
under which release is reachable for a room that recovers to the user's
comfort point. T9 in that suite pinned the buggy behavior and is corrected
by this deploy.)

Compounding path (same bug class): control_loop fed the LIVE setpoints into
_update_delivery_penalties, so during a hold every comfortable room (71-72F
vs the nudged 70) read as "past deadband and stuck", accrued a margin-lowering
delivery penalty, and further inflated worst_excess — deepening the latch.

THE FIX: while a nudge we own is trusted live (the SAME owned+readback-matches
predicate `_active_nudge_baseline` already uses for vent scoring), the nudge's
own worst_excess loop scores off_target against the recorded pre-nudge
BASELINE, and control_loop feeds the baseline-aware effective setpoints into
_update_delivery_penalties. Engage (not-owned path) is unchanged — live IS
the user's baseline there. Release still only ever fires from the branch where
the cloud-truth readback matches our own commanded value, so the never-pop-a-
user-hold safety (TRAP 2) is untouched.

This suite reproduces the production latch end-to-end (scenario P) and fails
on the pre-fix code.

No pytest / appdaemon needed: same stub pattern as the other tests in tests/.
"""
import sys
import types
from datetime import datetime, timedelta

# ---- stub appdaemon module BEFORE importing the controller -------------------
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")
class _Hass:
    def __init__(self, *a, **k): pass
hassapi.Hass = _Hass
for _mn, _m in [("appdaemon", types.ModuleType("appdaemon")),
                ("appdaemon.plugins", types.ModuleType("appdaemon.plugins")),
                ("appdaemon.plugins.hass", types.ModuleType("appdaemon.plugins.hass"))]:
    sys.modules[_mn] = _m
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

sys.path.insert(0, "/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps")
import smart_vent_controller as svc  # noqa: E402

# The mechanism is live in production (SETPOINT_NUDGE_ENABLED=True since
# 2026-09-02); assert that here so this suite can't silently go stale if the
# flag flips again.
assert svc.SETPOINT_NUDGE_ENABLED is True, (
    "suite assumes the nudge is enabled; revisit if the flag changed")


# ---- fake HA backend (full instance-state stub) -------------------------------
class FakeHA(svc.SmartVentController):
    """Full-state offline stub (the known AttributeError gotcha on this file:
    a partial stub blows up deep inside a pass that never mentions the missing
    field). Seeds every attribute initialize() seeds."""

    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=72.0, sp_heat=64.0):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 6, 8, 30, 0)
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
        self._nudge_persist_disable = True   # offline: no state-file writes
        self._nudge_restore_pending = False
        self._fan_assist_active = False
        self._cooling_ended_at = None
        self._cooling_started_at = None
        self._last_hvac_action = None
        self._coil_emergency_latched = False
        self._coil_emergency_since = None
        self._coil_ratio_current = None
        self._coil_ratio_changed_at = None
        self._coil_sensor_fail_count = 0
        self.sp_calls = []
        self.logs = []
        self._mode = mode
        self._hvac_mode = hvac_mode
        self._hvac_action = hvac_action
        self._sp_cool = sp_cool
        self._sp_heat = sp_heat
        # Every room neutral at 68.0 and unoccupied (below every active axis).
        for zn, zone in svc.ZONES.items():
            for rn, s in zone["rooms"].items():
                self.states[s["temp"]] = 68.0
                if s.get("occupancy"):
                    self.states[s["occupancy"]] = "off"
                for v in s.get("vents", []):
                    self.attrs[(v, "current_tilt_position")] = 100
        # Humidity conditions that pass the pre-cool gate (irrelevant in the
        # daytime scenarios, but keeps the gate well-defined).
        self.states[svc.PRECOOL_DEWPOINT_ENTITY] = 50.0
        self.states[svc.PRECOOL_HUMIDITY_ENTITY] = 50.0
        # control_loop's entry gates: master enable + Auto mode.
        self.states[svc.ENABLED_SWITCH] = "on"
        self.states[svc.MODE_SELECT] = mode
        self._set_thermostat()

    # ---- time ----------------------------------------------------------------
    def datetime(self, aware=False):
        return self._clock

    def advance(self, seconds):
        self._clock += timedelta(seconds=seconds)

    # ---- HA primitives ---------------------------------------------------------
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

    # ---- thermostat -----------------------------------------------------------
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
        # Cloud-truth setpoint sensors mirror the live setpoints (an ecobee
        # write echo appears on BOTH). Ownership decisions follow THESE.
        self.states[svc.SETPOINT_TRUTH_COOL] = self._sp_cool
        self.states[svc.SETPOINT_TRUTH_HEAT] = self._sp_heat

    def set_live_setpoints(self, cool=None, heat=None):
        """Simulate the live readback changing (our echo or a user change).
        Keeps mirror + cloud truth in sync, exactly like a real echo."""
        if cool is not None:
            self._sp_cool = float(cool)
        if heat is not None:
            self._sp_heat = float(heat)
        self._set_thermostat()

    def echo_our_command(self):
        """The ecobee echoes back exactly what we commanded (both sensors)."""
        self.set_live_setpoints(cool=self._sp_commanded_cool,
                                heat=self._sp_commanded_heat)

    def set_hvac_action(self, action):
        self._hvac_action = action
        self._set_thermostat()

    def set_room_temp(self, zone, room, temp):
        self.states[svc.ZONES[zone]["rooms"][room]["temp"]] = float(temp)

    def occupy(self, zone, room):
        self.states[svc.ZONES[zone]["rooms"][room]["occupancy"]] = "on"
        self._zone_last_occupied[zone] = self._clock  # zone presence

    def set_room(self, zone, room, temp, occupied):
        self.set_room_temp(zone, room, temp)
        if occupied:
            self.occupy(zone, room)

    def run_nudge(self, with_precool=True):
        """One control-loop-shaped nudge cycle (same shape as
        test_precool_nudge_integration.run_cycle)."""
        gate = self._precool_gate() if with_precool else None
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat,
                                          self._mode, precool_gate=gate)


def find_key(room):
    for zn, zone in svc.ZONES.items():
        if room in zone["rooms"]:
            return (zn, room)
    raise KeyError(room)


PASS = []
def check(name, cond):
    PASS.append(bool(cond))
    print(("PASS - " if cond else "FAIL - ") + name)


def setpoint_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/resume_top_event"]


GR = ("upstairs", "Game Room")


# =============================================================================
# P. THE PRODUCTION LATCH, end-to-end (RED on pre-fix code):
#    - baseline cool 72 (schedule), Game Room occupied and hot -> engage at
#      excess-vs-72 (room 75.9 -> off 3.9, margin 1.5, excess 2.4), command
#      cool 70 (saturated 2F cap).
#    - ecobee echoes 70; compressor runs.
#    - Game Room plateaus at 73.0 — it has RECOVERED to within margin of the
#      USER's 72 baseline (off-vs-72 1.0, excess-vs-72 0.0 <= release 0.5),
#      the exact recovery the mechanism exists to wait for. Against the NUDGED
#      70 it reads off 3.0 / excess 1.5 — exactly the ENGAGE threshold — so the
#      pre-fix code can never release. THIS is the 15-hour hold.
#    - Run a full simulated DAY of 2-minute cycles (720 cycles) at that
#      plateau: the fixed code must release within the first few cycles; the
#      pre-fix code holds all 720 (reproducing "only the schedule ever pops
#      it").
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 75.9, True)          # excess vs 72: (75.9-72)-1.5 = 2.4
ha.run_nudge()                        # engage
check("P engage: exactly one set_hold", len(setpoint_calls(ha)) == 1)
check("P engage: commanded cool 70 (baseline 72 - saturated 2F cap)",
      ha._sp_commanded_cool == 70.0)
check("P engage: baseline captured 72", ha._sp_baseline_cool == 72.0)
ha.echo_our_command()                 # live readback now 70 (both sensors)
ha.advance(120)
# The room plateaus at 73.0: recovered vs the USER's baseline (excess 0.0),
# still 'hot' vs our own nudged 70 (excess 1.5). Production shape all week.
ha.set_room(*GR, 73.0, True)
released_at = None
for i in range(720):                  # a full simulated day of 2-min cycles
    ha.advance(120)
    ha.run_nudge()
    if ha._sp_owned is False:
        released_at = i
        break
check("P LATCH FIX: the nudge RELEASES once the room recovers to the user's "
      "baseline (not after 720 cycles of the pre-fix latch)",
      released_at is not None and released_at < 720)
if released_at is not None:
    print(f"    released after {released_at + 1} cycles "
          f"({(released_at + 1) * 2} min of simulated plateau)")
check("P LATCH FIX: exactly ONE resume_top_event issued on release",
      len(resume_calls(ha)) == 1)
check("P LATCH FIX: no additional set_hold writes after the release",
      len(setpoint_calls(ha)) == 1)
check("P LATCH FIX: ownership fully cleared",
      ha._sp_owned is False and ha._sp_baseline_cool is None
      and ha._sp_mismatch_since is None and ha._sp_heating is None)
check("P LATCH FIX: release is explained in the log by the baseline frame",
      any("released" in m and "0.00" in m for m in ha.logs))

# Control group: the SAME plateau scenario must NOT release while the room is
# still genuinely hot vs the baseline (75.9 held -> excess 2.4 >> release).
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 75.9, True)
ha.run_nudge()
ha.echo_our_command()
ha.advance(120)
for _ in range(10):                   # ~20 min: far less than a dwell window
    ha.advance(120)
    ha.run_nudge()
check("P control: still genuinely hot vs baseline -> nudge NOT released",
      ha._sp_owned is True and len(resume_calls(ha)) == 0)
check("P control: no deepen writes (single fixed cap; deepen is a no-op)",
      len(setpoint_calls(ha)) == 1)

# =============================================================================
# H. REAL HYSTERESIS BAND, measured against the baseline: with the room at
#    73.5 (off-vs-72 1.5, excess 0.0... wait — margin 1.5 -> excess 0.0) use
#    74.2 instead: off 2.2 - margin 1.5 = excess 0.7, INSIDE the release 0.5 /
#    engage 1.5 band -> held, neither released nor re-engaged, zero calls.
#    Pre-fix code, scoring vs the nudged 70, would read excess 2.7 and keep
#    hammering (owned, no-op only because deepen is capped — but the RELEASE
#    gate can never see this band at all).
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 75.9, True)
ha.run_nudge()
ha.echo_our_command()
ha.advance(120)
ha.set_room(*GR, 74.2, True)          # excess vs baseline 72: 2.2-1.5 = 0.7
ha.advance(120)
ha.run_nudge()
check("H hysteresis: excess 0.7 (between release 0.5 and engage 1.5, vs the "
      "BASELINE) -> held, zero new calls",
      ha._sp_owned is True and len(resume_calls(ha)) == 0
      and len(setpoint_calls(ha)) == 1)

# ...and just above the engage line vs baseline (75.6 -> off 3.6, excess 2.1)
# it stays owned with no deepen (cap already commanded) — the band is real.
ha.set_room(*GR, 75.6, True)
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC + 120)
ha.run_nudge()
check("H hysteresis: excess 2.1 vs baseline -> still owned, no deepen "
      "(single fixed cap)", ha._sp_owned is True
      and len(setpoint_calls(ha)) == 1 and len(resume_calls(ha)) == 0)

# =============================================================================
# E. ENGAGE FRAME UNCHANGED (not-owned path): worst_excess is still measured
#    against the LIVE setpoint, which when we own nothing IS the user's
#    effective baseline (schedule or manual). A hot occupied room engages at
#    the same threshold as before — this fix must not move the engage line.
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 74.9, True)          # excess vs live 72: 2.9-1.5 = 1.4 < 1.5
ha.run_nudge()
check("E engage frame: excess 1.4 vs live 72 (not owned) -> NO engage "
      "(unchanged)", len(setpoint_calls(ha)) == 0)
ha.set_room(*GR, 75.0, True)          # excess exactly 1.5 -> engages
ha.run_nudge()
check("E engage frame: excess 1.5 vs live 72 -> engages (unchanged threshold)",
      len(setpoint_calls(ha)) == 1 and ha._sp_commanded_cool == 70.0)

# =============================================================================
# S. SAFETY: release is STILL readback-guarded. Owned + the cloud-truth
#    readback DIVERGES from our command (a human's hold is now on top) + the
#    room has recovered vs the baseline -> NO resume_top_event, ownership
#    follows the existing mismatch/confirm machinery. The baseline-referenced
#    release must never pop a user's hold (TRAP 2).
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 75.9, True)
ha.run_nudge()                        # engage, commanded 70
# The USER raises the setpoint to 73 (their hold is now the top event).
ha.set_live_setpoints(cool=73.0, heat=64.0)
ha.advance(120)
ha.run_nudge()                        # fresh mismatch -> confirm window opens
check("S safety: fresh mismatch -> still owned, no resume",
      ha._sp_owned is True and len(resume_calls(ha)) == 0)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()                        # confirmed override -> relinquish
check("S safety: confirmed override -> relinquished via the OVERRIDE path "
      "(cooldown latched), NOT a release",
      ha._sp_owned is False and len(resume_calls(ha)) == 0
      and ha._sp_override_cooldown_until is not None)

# =============================================================================
# D. DELIVERY-PENALTY FRAME (Fix B): during a trusted hold, a COMFORTABLE
#    donor room (71.5F vs the user's 72 baseline, i.e. NOT past deadband) must
#    NOT accrue a delivery penalty just because the live nudged setpoint is
#    70. Pre-fix code fed the LIVE setpoints into _update_delivery_penalties,
#    so 71.5 read as +1.5 past the nudged deadband and the room was flagged
#    "stuck" while merely comfortable -> margin erosion -> deeper latch.
#    Driven through control_loop's exact call shape.
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha.set_room(*GR, 75.9, True)          # hot room drives the engage
# A comfortable occupied donor: 71.5 vs baseline 72 (off -0.5), wide open.
lr = find_key("Living Room")
ha.set_room(*lr, 71.5, True)
for v in svc.ZONES[lr[0]]["rooms"][lr[1]]["vents"]:
    ha.attrs[(v, "current_tilt_position")] = 100
ha.run_nudge()                        # engage (cool 70)
ha.echo_our_command()
# control_loop itself must feed the BASELINE-AWARE effective setpoints into
# _update_delivery_penalties while a nudge is trusted. Drive the REAL
# control_loop (not a hand-computed eff) so the pre-fix LIVE-frame wiring
# fails this check. TWO control-loop cycles with the temp held flat (the
# first only records the prior sample; the stuck-rate judgment needs the
# second).
check("D setup: effective setpoints are the BASELINE 72 while trusted",
      ha._active_nudge_baseline(*ha._get_thermostat_state()[2:]) == (72.0, 64.0))
ha.control_loop(None)                 # cycle 1 (records prior samples)
ha.advance(120)
ha.control_loop(None)                 # cycle 2 (judges the stuck rate)
p_after_fix = ha._delivery_penalty.get(lr, 0.0)
# The pre-fix frame for contrast: feed the LIVE nudged setpoints directly
# into the delivery pass — exactly what the old control_loop wiring did.
ha2 = FakeHA(sp_cool=72.0, sp_heat=64.0)
ha2.set_room(*GR, 75.9, True)
ha2.set_room(*lr, 71.5, True)
for v in svc.ZONES[lr[0]]["rooms"][lr[1]]["vents"]:
    ha2.attrs[(v, "current_tilt_position")] = 100
ha2.run_nudge()
ha2.echo_our_command()
ha2._update_delivery_penalties("cooling",
                               ha2._get_thermostat_state()[2],
                               ha2._get_thermostat_state()[3])
ha2.advance(120)
ha2._update_delivery_penalties("cooling",
                               ha2._get_thermostat_state()[2],
                               ha2._get_thermostat_state()[3])
p_live_frame = ha2._delivery_penalty.get(lr, 0.0)
check("D delivery frame: comfortable donor (71.5 vs baseline 72) accrues NO "
      "penalty under the baseline frame",
      p_after_fix < 0.01)
check("D delivery frame: the LIVE frame WOULD have penalized it (bug "
      "confirmed — this is what inflated worst_excess all week)",
      p_live_frame > 0.0)

# =============================================================================
# V. NO-NUDGE IDENTITY: with nothing owned, effective == live, so the delivery
#    pass behaves byte-identically whether fed live or effective values.
# =============================================================================
ha = FakeHA(sp_cool=72.0, sp_heat=64.0)
check("V identity: no nudge -> _active_nudge_baseline returns None",
      ha._active_nudge_baseline(72.0, 64.0) is None)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)