"""Offline validation of the setpoint-nudge (TRIGGER) axis.

Encodes the acceptance assertions for the 2026-08-31 setpoint-nudge mechanism:
when an OCCUPIED room's measured excess over its activation margin (`off_target
- _room_margin`, the same measured quantity _zone_contention already uses) is
large enough that the flat whole-house ecobee average would be satisfied while
that room bakes, the app temporarily moves the thermostat setpoint (cooling:
drop the cool setpoint; heating: raise the heat setpoint) so the compressor
actually escalates. It then owns/releases that hold through a strict state
machine, matching LIVE readback against what it commanded.

The 14 scenarios cover: engagement, magnitude + quantization, the hard cap,
dwell, release, hysteresis, the confirmed-vs-echo user-override distinction
(and never fighting the user / never popping their hold), heating symmetry, the
heatCoolMinDelta gap coupling, vacant-zone exclusion, the disabled/non-Auto
guard, re-nudging off the ORIGINAL baseline (no unbounded ratchet), and the
full occupancy/presence pipeline reuse.

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


# ---- fake HA backend ---------------------------------------------------------
class FakeHA(svc.SmartVentController):
    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=70.0, sp_heat=64.0):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 8, 31, 18, 0, 0)
        # Handicap axes (default clean: no supply/delivery penalities).
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        # Zone-presence state (so _zone_is_vacant / _effective_occupancy_override
        # work without initialize()).
        self._zone_last_occupied = {}
        self._zone_occupied = {}
        self._zone_vacancy_demoted = set()
        # Setpoint-nudge ownership state (what initialize() would seed).
        self._sp_owned = False
        self._sp_commanded_cool = None
        self._sp_commanded_heat = None
        self._sp_baseline_cool = None
        self._sp_baseline_heat = None
        self._sp_last_write_ts = None
        self._sp_mismatch_since = None
        self._sp_heating = None
        # Record every service call: list of (service, kwargs).
        self.sp_calls = []
        self.logs = []
        self._mode = mode
        self._hvac_mode = hvac_mode
        self._hvac_action = hvac_action
        self._sp_cool = sp_cool if sp_cool is not None else None
        self._sp_heat = sp_heat if sp_heat is not None else None
        # Populate zone rooms with a neutral temp + occupancy "off". 68.0F is
        # deliberately chosen to be OUT of reach of every active axis so passive
        # rooms can never drive the worst_excess signal: below the cooling
        # setpoint (70), and under the heating PIR override (off < 3.0 vs heat
        # setpoint 70). After a nudge to cool 67.5 a room at 68 reads off 0.5
        # -> comfortably under OCCUPANCY_OVERRIDE_OVER, so it stays silent.
        for zn, zone in svc.ZONES.items():
            for rn, s in zone["rooms"].items():
                self.states[s["temp"]] = 68.0
                if s.get("occupancy"):
                    self.states[s["occupancy"]] = "off"
        self._set_thermostat()

    # ---- time ----------------------------------------------------------------
    def datetime(self, aware=False):
        return self._clock

    def advance(self, seconds):
        self._clock += timedelta(seconds=seconds)

    # ---- HA primitives --------------------------------------------------------
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

    # ---- helpers --------------------------------------------------------------
    def _set_thermostat(self):
        # HA climate entities report `state` = the HVAC MODE string, so for a
        # dual-setpoint thermostat _get_thermostat_state() returns
        # hvac_mode="heat_cool" and the TRAP-1 gap coupling is active.
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

    def live_cool(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"]

    def live_heat(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_low"]

    def set_room_temp(self, zone, room, temp):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["temp"]] = float(temp)

    def occupy(self, zone, room):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["occupancy"]] = "on"

    def set_live_setpoints(self, cool=None, heat=None):
        """Simulate the ecobee readback changing (our echo or a user change)."""
        a = self.attrs[(svc.THERMOSTAT, "all")]["attributes"]
        if cool is not None:
            a["target_temp_high"] = float(cool)
        if heat is not None:
            a["target_temp_low"] = float(heat)

    def set_hvac_action(self, action):
        """Flip the thermostat's hvac_action (e.g. to 'idle' / 'fan')."""
        a = self.attrs[(svc.THERMOSTAT, "all")]["attributes"]
        a["hvac_action"] = action
        self._hvac_action = action

    def run_nudge(self):
        """Drive one _apply_setpoint_nudge cycle; the call sites always pass
        the LIVE hvac_mode/action/setpoints from _get_thermostat_state."""
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat, self._mode)


def build_occupied_room(zone="upstairs", room="Game Room", temp=None,
                        sp_cool=70.0, **kw):
    """A thermostat in cooling with room OCCUPIED at `temp` (default hot 77F)."""
    ha = FakeHA(sp_cool=sp_cool, **kw)
    ha.occupy(zone, room)
    ha.set_room_temp(zone, room, temp if temp is not None else 77.0)
    return ha


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


def setpoint_calls(ha):
    """Return only ecobee_enhanced/set_hold_temperature calls."""
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    """Return only ecobee_enhanced/resume_top_event calls."""
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/resume_top_event"]


def nudge_amount(w):
    import math
    v = max(0.0, min(w * svc.SETPOINT_NUDGE_GAIN, svc.SETPOINT_NUDGE_MAX_F))
    return math.floor(v / svc.SETPOINT_NUDGE_STEP_F) * svc.SETPOINT_NUDGE_STEP_F


# =============================================================================
# 1. NO OCCUPIED ROOM OVER THE ENGAGE THRESHOLD -> zero service calls,
#    _sp_owned stays False.
# =============================================================================
# Game Room at just under the engage excess (worst_excess < 1.5):
#   off = temp - 70; margin = 1.5; excess = off - 1.5 < 1.5 -> off < 3.0 -> temp < 73.0
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=72.5, sp_cool=70.0)
ha.run_nudge()
check("T1 below engage: exactly zero service calls",
      len(ha.sp_calls) == 0)
check("T1 below engage: _sp_owned stays False", ha._sp_owned is False)

# =============================================================================
# 2. OCCUPIED ROOM WITH worst_excess 5.5 -> exactly ONE set_hold_temperature;
#    cool_temp_f == baseline_cool - nudge(5.5); _sp_owned True.
#    off = temp-70; margin=1.5; excess=5.5 -> off=7.0 -> temp=77.0
#    nudge(5.5) = floor(5.5*0.5/0.5)*0.5 = 2.5; basline cool 70 -> 67.5
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()
writes = setpoint_calls(ha)
check("T2 engage: exactly ONE set_hold_temperature call", len(writes) == 1)
check("T2 engage: no resume calls", len(resume_calls(ha)) == 0)
if writes:
    kw = writes[0]
    check("T2 cool_temp_f == baseline_cool - nudge(5.5)",
          kw["cool_temp_f"] == 70.0 - nudge_amount(5.5))
    # TRAP 1 in heat_cool: dropping cool to 68.0 must drag heat down to
    # 68.0 - 6.0 = 62.0 so the min heatCoolMinDelta gap is preserved.
    check("T2 heat_temp_f == 62.0 (dragged to preserve 6F gap)",
          kw["heat_temp_f"] == 62.0)
    check("T2 hold_type == nextTransition", kw["hold_type"] == "nextTransition")
check("T2 _sp_owned True", ha._sp_owned is True)
check("T2 _sp_baseline_cool captured live 70.0", ha._sp_baseline_cool == 70.0)
check("T2 _sp_commanded_cool recorded", ha._sp_commanded_cool == 68.0)

# =============================================================================
# 3. NUDGE IS CAPPED: worst_excess 20.0 -> commanded cool never more than
#    SETPOINT_NUDGE_MAX_F below baseline.
#    off = temp-70; excess=20 -> off=21.5 -> temp=91.5 (absurd, but the cap is
#    independent of reality — that's exactly what we assert).
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=91.5, sp_cool=70.0)
ha.run_nudge()
writes = setpoint_calls(ha)
check("T3 cap: exactly one write", len(writes) == 1)
if writes:
    check("T3 commanded cool >= baseline - MAX",
          writes[0]["cool_temp_f"] >= 70.0 - svc.SETPOINT_NUDGE_MAX_F)

# =============================================================================
# 4. OWNED + READBACK MATCHES + room unchanged + dwell NOT elapsed -> no new
#    service calls. Seed ownership at nudge 2.5 (cool 67.5), live readback
#    matches, room stays at excess 5.5, no dwell elapsed.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage -> 1 write, owned, cool 67.5
# ecobee echoes our hold back.
ha.set_live_setpoints(cool=67.5, heat=64.0)
# Room unchanged (still excess 5.5). Advance some but < dwell.
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC // 2)
ha.run_nudge()
check("T4 dwell: zero NEW service calls", len(ha.sp_calls) == 1)

# =============================================================================
# 5. OWNED + READBACK MATCHES + worst_excess 0.2 (<= RELEASE) -> exactly ONE
#    resume_top_event, _sp_owned False, all _sp_* cleared.
#    Note: after our hold lands, the LIVE cool setpoint IS our commanded value
#    (67.5), and worst_excess is measured against that live setpoint. So the
#    room must cool toward the NUDGED setpoint to release: to reach excess 0.2
#    (off - margin = 0.2, margin 1.5 -> off 1.7), room temp = 67.5 + 1.7 = 69.2.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, commanded cool 67.5
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC)  # dwell elapsed (irrelevant for release)
ha.set_room_temp("upstairs", "Game Room", 69.2)  # excess 0.2 vs live 67.5
ha.run_nudge()
res = resume_calls(ha)
writes = setpoint_calls(ha)
check("T5 release: exactly ONE resume_top_event", len(res) == 1)
check("T5 release: no additional set_hold writes", len(writes) == 1)
check("T5 release: _sp_owned False", ha._sp_owned is False)
check("T5 release: _sp_commanded_cool cleared", ha._sp_commanded_cool is None)
check("T5 release: _sp_baseline_cool cleared", ha._sp_baseline_cool is None)
check("T5 release: _sp_mismatch_since cleared", ha._sp_mismatch_since is None)

# =============================================================================
# 6. HYSTERESIS: owned + worst_excess 1.0 (between RELEASE 0.5 and ENGAGE 1.5)
#    -> NO release and NO re-nudge; stays owned, zero calls.
#    excess 1.0 -> off=2.5 -> temp=72.5
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC)
ha.set_room_temp("upstairs", "Game Room", 72.5)  # excess 1.0 (in the band)
ha.run_nudge()
check("T6 hysteresis: zero new calls (no release, no re-nudge)",
      len(ha.sp_calls) == 1)
check("T6 hysteresis: still owned", ha._sp_owned is True)

# =============================================================================
# 7. USER OVERRIDE, CONFIRMED: owned, live cool readback differs from commanded
#    by 2.0F, mismatch persists > CONFIRM -> _sp_owned False, ZERO resume calls,
#    ZERO set_hold writes, baseline NOT restored.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, commanded cool 67.5
# The USER raises the cool setpoint to 69.5 (2.0F above our commanded 67.5).
ha.set_live_setpoints(cool=69.5, heat=64.0)
ha.run_nudge()  # fresh mismatch -> set _sp_mismatch_since, no action
check("T7 fresh mismatch: zero service calls this cycle",
      len(ha.sp_calls) == 1)
check("T7 fresh mismatch: _sp_mismatch_since set", ha._sp_mismatch_since is not None)
# Mismatch persists past the confirm window.
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("T7 confirmed override: _sp_owned False", ha._sp_owned is False)
check("T7 confirmed override: ZERO resume_top_event calls", len(resume_calls(ha)) == 0)
check("T7 confirmed override: ZERO set_hold writes (never fight back)",
      len(setpoint_calls(ha)) == 1)
check("T7 confirmed override: baseline NOT restored (cool live 69.5, not 70)",
      ha.live_cool() == 69.5)

# =============================================================================
# 8. USER OVERRIDE, TRANSIENT ECHO: owned, mismatch on one cycle, matches again
#    on the next (within confirm window) -> ownership RETAINED,
#    _sp_mismatch_since cleared, zero calls.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, cool 68.0
# A transient echo mismatch (poll lag) shows 69.0 for ONE cycle...
ha.set_live_setpoints(cool=69.0, heat=64.0)
ha.run_nudge()
check("T8 echo: ownership still held on first mismatch",
      ha._sp_owned is True and ha._sp_mismatch_since is not None)
# ...then the readback settles to our commanded 68.0 on the next cycle.
ha.set_live_setpoints(cool=68.0, heat=64.0)
ha.run_nudge()
check("T8 echo: ownership RETAINED after readback re-matches",
      ha._sp_owned is True)
check("T8 echo: _sp_mismatch_since cleared", ha._sp_mismatch_since is None)
check("T8 echo: zero new service calls", len(ha.sp_calls) == 1)

# =============================================================================
# 9. HEATING SYMMETRY: heating mode, coldest occupied room below the heat
#    setpoint with worst_excess 4.0 -> heat setpoint moves UP by nudge(4.0)=2.0,
#    and the cool axis is NOT moved down. Uses the realistic heat_cool heating
#    mode (the ecobee this app targets lives in heat_cool year-round).
#    heat setpoint 70, margin 1.5, excess 4.0 -> off = 5.5 -> temp = 70-5.5=64.5.
#    nudge(4.0) = floor(4.0*0.5/0.5)*0.5 = 2.0 -> commanded_heat = 72.0.
#    TRAP 1 raises cool to preserve the gap (cool_baseline 75 -> max(75, 78)=78),
#    which is "not moved down".
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
            sp_cool=75.0, sp_heat=70.0)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 64.5)  # excess = (70-64.5) - 1.5 = 4.0
ha._set_thermostat()
ha.run_nudge()
writes = setpoint_calls(ha)
check("T9 heat: exactly one write", len(writes) == 1)
if writes:
    kw = writes[0]
    check("T9 heat_temp_f == baseline_heat + nudge(4.0) == 72.0",
          kw["heat_temp_f"] == 70.0 + nudge_amount(4.0))
    check("T9 heat_temp_f == 72.0", kw["heat_temp_f"] == 72.0)
    # Cool axis raised to preserve the min gap, NEVER moved down below baseline.
    check("T9 cool axis NOT moved down (>= baseline_cool)",
          kw["cool_temp_f"] >= 75.0)
    check("T9 gap preserved (cool - heat >= 6F)",
          kw["cool_temp_f"] - kw["heat_temp_f"] >= svc.SETPOINT_HEATCOOL_MIN_DELTA_F)

# =============================================================================
# 10. MIN DELTA: heat_cool mode, baseline cool=70 heat=64, nudge cool down 1.0
#     -> the SAME service call must ALSO send heat_temp_f <= 63.0 so the 6F gap
#     is preserved.
#     nudge 1.0 -> excess where nudge_amount = 1.0 -> floor(excess*0.5/1.0)==1
#     -> excess in [2.0, 4.0). Use excess 3.5:
#     nudge = floor(3.5*0.5/1.0)*1.0 = 1.0 -> cool 70-1.0=69.0.
#     commanded_heat = min(64, 69.0-6) = min(64,63.0) = 63.0.
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling", sp_cool=70.0, sp_heat=64.0)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 70 + 5.0)  # excess = 5.0-1.5=3.5
ha._set_thermostat()
ha.run_nudge()
writes = setpoint_calls(ha)
check("T10 mindelta: exactly one write", len(writes) == 1)
if writes:
    kw = writes[0]
    check("T10 cool_temp_f == 69.0 (whole degree)", kw["cool_temp_f"] == 69.0)
    check("T10 cold-cool drags heat down to preserve 6F gap",
          kw["heat_temp_f"] <= 63.0)
    check("T10 gap preserved (cool - heat >= 6F)",
          kw["cool_temp_f"] - kw["heat_temp_f"] >= svc.SETPOINT_HEATCOOL_MIN_DELTA_F)

# =============================================================================
# 11. VACANT ZONE: the only struggling room IS in a VACANT (unoccupied) zone ->
#     zero service calls (a vacant zone must never drive the compressor).
#     Game Room temp 77, occupancy "off", no zone has an occupied room.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.states[svc.ZONES["upstairs"]["rooms"]["Game Room"]["occupancy"]] = "off"
ha.run_nudge()  # Game Room is genuinely hot but its zone is vacant -> excluded
check("T11 vacant zone: zero service calls", len(ha.sp_calls) == 0)
check("T11 vacant zone: _sp_owned stays False", ha._sp_owned is False)

# =============================================================================
# 12. GUARD: controller disabled, OR mode != "Auto" -> zero calls regardless of
#     how hot any room is. (Enabled gate is enforced by control_loop; the mode
#     gate is re-checked inside _apply_setpoint_nudge.)
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=91.5, sp_cool=70.0)
ha._mode = "Manual"
ha.run_nudge()
check("T12 guard (Manual): zero service calls", len(ha.sp_calls) == 0)
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=91.5, sp_cool=70.0)
ha._mode = "Cool Upstairs"
ha.run_nudge()
check("T12 guard (Cool Upstairs): zero service calls", len(ha.sp_calls) == 0)

# =============================================================================
# 13. RE-NUDGE OFF BASELINE: owned at nudge 1.0, room worsens, dwell elapsed ->
#     new commanded cool = baseline - larger_nudge, NOT previous_commanded -
#     larger_nudge (no unbounded ratchet).
#     Engage at excess 2.5 (nudge 1.0 -> cool 69.0). Readback echoes 69.0.
#     Room worsens to excess 6.0 (nudge 3.0 -> cool 67.0). After dwell, the
#     new command must be 67.0 (baseline 70 - 3.0), not 66.0 (69 - 3.0).
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room",
                         temp=70.0 + svc.PRIORITY_MARGIN_BASE + 2.5, sp_cool=70.0)
# excess 2.5 -> nudge = floor(2.5*.5/.5)*.5 = 1.0 -> cool 69.0
ha.run_nudge()
writes1 = setpoint_calls(ha)
check("T13 initial nudge: cool 69.0", len(writes1) == 1 and writes1[0]["cool_temp_f"] == 69.0)
# Echo our hold; dwell elapses.
ha.set_live_setpoints(cool=69.0, heat=64.0)
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC + 1)
# Room worsens to excess 6.0: temp = 70 + 1.5 + 6.0 = 77.5 -> nudge 3.0 -> cool 67.0
ha.set_room_temp("upstairs", "Game Room", 77.5)
ha.run_nudge()
writes2 = setpoint_calls(ha)
check("T13 re-nudge: exactly one MORE write (2 total)",
      len(writes2) == 2)
if len(writes2) == 2:
    check("T13 re-nudge off ORIGINAL baseline: cool == 70 - 3.0 = 67.0 (not 66.0)",
          writes2[1]["cool_temp_f"] == 67.0)

# =============================================================================
# 14. NO-REGRESSION is covered by running the OTHER five suites; this file just
#     confirms the new method leaves unrelated state paths intact by engaging
#     and releasing cleanly through the full cycle (see T5).
# =============================================================================

# =============================================================================
# 15. IDLE + OWNED + READBACK MATCHES + room STILL HOT (worst_excess 4.0, well
#     above RELEASE) -> ZERO service calls; _sp_owned stays True; the nudge is
#     RETAINED. Proves we no longer drop the nudge just because the compressor
#     happens to be between cycles (the old code released on every idle
#     transition, oscillating the hold / write-churning).
#     Engage (cool 67.5, 1 write), echo the hold back, then the compressor
#     satisfies and drops to idle. Room is still hot: vs live cool 67.5,
#     temp 73.0 -> excess = (73.0-67.5)-1.5 = 4.0; nudge_amount(4.0)=2.0, which
#     WOULD deepen (67.0 < 67.5) but only if conditioning — idle must suppress it.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage -> 1 write, owned, _sp_heating False (cool)
assert ha._sp_owned is True
assert ha._sp_heating is False
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.set_hvac_action("idle")  # compressor satisfies, drops to idle
ha.set_room_temp("upstairs", "Game Room", 73.0)  # excess 4.0 vs live 67.5
ha.run_nudge()
check("A idle+hot: ZERO service calls this cycle (no release, no deepen)",
      len(ha.sp_calls) == 1)
check("A idle+hot: _sp_owned stays True (nudge retained)",
      ha._sp_owned is True)
check("A idle+hot: no resume calls", len(resume_calls(ha)) == 0)
check("A idle+hot: no set_hold writes", len(setpoint_calls(ha)) == 1)

# =============================================================================
# 16. IDLE + OWNED + READBACK MATCHES + room RECOVERED (worst_excess 0.2, <=
#     RELEASE) -> exactly ONE resume_top_event; _sp_owned False; all _sp_*
#     cleared. Proves a genuine recovery still releases cleanly WHILE idle.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, cool 67.5
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.set_hvac_action("idle")
ha.set_room_temp("upstairs", "Game Room", 69.2)  # excess 0.2 vs live 67.5
ha.run_nudge()
res = resume_calls(ha)
check("B idle+recovered: exactly ONE resume_top_event", len(res) == 1)
check("B idle+recovered: _sp_owned False", ha._sp_owned is False)
check("B idle+recovered: _sp_commanded_cool cleared", ha._sp_commanded_cool is None)
check("B idle+recovered: _sp_baseline_cool cleared", ha._sp_baseline_cool is None)
check("B idle+recovered: _sp_mismatch_since cleared", ha._sp_mismatch_since is None)
check("B idle+recovered: _sp_heating cleared", ha._sp_heating is None)

# =============================================================================
# 17. THE REGRESSION THAT MOTIVATED THIS FIX: IDLE + OWNED + USER CHANGED THE
#     SETPOINT (live cool readback differs from _sp_commanded_cool by 2.0F),
#     mismatch first seen THIS cycle -> ZERO resume, ZERO set_hold, still owned
#     (inside the confirm window), _sp_mismatch_since now set. The old idle path
#     fired resume_top_event here, popping the USER's hold.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, commanded cool 67.5
# The USER changes the cool setpoint to 69.5 (2.0F above our commanded) via the
# ecobee app; their change becomes the top event. THEN the compressor drops to idle.
ha.set_live_setpoints(cool=69.5, heat=64.0)
ha.set_hvac_action("idle")
ha.run_nudge()  # fresh mismatch, first seen this cycle
check("C idle+user-change, fresh mismatch: ZERO resume_top_event",
      len(resume_calls(ha)) == 0)
check("C idle+user-change, fresh mismatch: ZERO set_hold writes",
      len(setpoint_calls(ha)) == 1)
check("C idle+user-change, fresh mismatch: _sp_owned still True (confirm window)",
      ha._sp_owned is True)
check("C idle+user-change, fresh mismatch: _sp_mismatch_since now set",
      ha._sp_mismatch_since is not None)

# =============================================================================
# 18. Same as 17 but the mismatch has PERSISTED past SETPOINT_NUDGE_CONFIRM_SEC:
#     _sp_owned becomes False, and STILL zero resume / zero set_hold. We
#     relinquish silently — never pop the user's hold, never fight back.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room", temp=77.0, sp_cool=70.0)
ha.run_nudge()  # engage, commanded cool 67.5
ha.set_live_setpoints(cool=69.5, heat=64.0)  # user's change
ha.set_hvac_action("idle")
ha.run_nudge()  # fresh mismatch -> sets _sp_mismatch_since
assert ha._sp_mismatch_since is not None
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)  # mismatch persists past confirm
ha.run_nudge()
check("D idle+user-change, confirmed: _sp_owned False",
      ha._sp_owned is False)
check("D idle+user-change, confirmed: ZERO resume_top_event",
      len(resume_calls(ha)) == 0)
check("D idle+user-change, confirmed: ZERO set_hold writes (never fight back)",
      len(setpoint_calls(ha)) == 1)
check("D idle+user-change, confirmed: _sp_heating cleared", ha._sp_heating is None)

# =============================================================================
# 19. IDLE + NOT owned + a very hot occupied room (worst_excess 6.0): ZERO
#     service calls. We never engage a brand-new nudge while the system is idle.
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="idle", sp_cool=70.0, sp_heat=64.0)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 70.0 + svc.PRIORITY_MARGIN_BASE + 6.0)
ha._set_thermostat()  # idle + excess 6.0 (temp 77.5)
ha.run_nudge()
check("E idle+not-owned+hot: ZERO service calls (no engage while idle)",
      len(ha.sp_calls) == 0)
check("E idle+not-owned+hot: _sp_owned stays False", ha._sp_owned is False)

# =============================================================================
# 20. IDLE + OWNED + readback matches + room WORSENS substantially + dwell fully
#     elapsed -> ZERO set_hold_temperature calls (no deepening while idle). The
#     hold rides out the idle period; deepening only happens on the next real
#     conditioning cycle.
#     Engage at excess 2.5 (nudge 1.0 -> cool 69.0), echo, idle, then the room
#     worsens so a deeper nudge IS warranted (vs live 69.0: temp 76.5 ->
#     excess 6.0 -> new cool 67.0 < 69.0, would deepen if conditioning) AND the
#     dwell has elapsed. Idle must still suppress the deepen.
# =============================================================================
ha = build_occupied_room(zone="upstairs", room="Game Room",
                         temp=70.0 + svc.PRIORITY_MARGIN_BASE + 2.5, sp_cool=70.0)
ha.run_nudge()  # engage, cool 69.0 (1 write)
assert len(setpoint_calls(ha)) == 1
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.set_hvac_action("idle")
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC + 1)  # dwell elapsed
ha.set_room_temp("upstairs", "Game Room", 69.0 + svc.PRIORITY_MARGIN_BASE + 6.0)  # excess 6.0
ha.run_nudge()
check("F idle+owned+worsened+dwell elapsed: ZERO deepen writes",
      len(setpoint_calls(ha)) == 1)
check("F idle+owned+worsened+dwell elapsed: ZERO resume (still hot)",
      len(resume_calls(ha)) == 0)
check("F idle+owned+worsened+dwell elapsed: still owned",
      ha._sp_owned is True)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
