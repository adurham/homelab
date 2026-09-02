"""Offline regression guard for the HALF-DEGREE SETPOINT RATCHET.

ROOT CAUSE (2026-09-01, from the live host): the ecobee stores/reports
setpoints as WHOLE DEGREES only. The nudge quantized nudge_amount to 0.5F
steps (SETPOINT_NUDGE_STEP_F=0.5), so it commanded values like 71.5 / 68.5
that the thermostat cannot represent. The readback came back as the nearest
whole degree (71 / 69), a 0.5F gap that cleared the readback-match tolerance
(SETPOINT_NUDGE_TOLERANCE_F=0.2), so the app concluded "the user changed the
setpoint", adopted its OWN nudge residue as the new baseline, and nudged again:

  09:28:01  engaged (cool) worst_excess 3.35F, nudge to cool 71.5F heat 64.0F
            (baseline cool 73.0 heat 64.0)
  09:38:01  user changed setpoint (cool 71.5 -> 71 live), relinquishing
            ownership without resuming
  09:40:02  engaged (cool) worst_excess 5.84F, nudge to cool 68.5F heat 62.5F
            (baseline cool 71.0 heat 64.0)
  09:50:01  user changed setpoint (cool 68.5 -> 69 live), relinquishing ...
  -> the house walked 73 -> 71 -> 69 -> 66.

FIX: quantify the nudge to WHOLE degrees (SETPOINT_NUDGE_STEP_F=1.0). The
baseline is already a whole degree, so commanded == readback exactly and
ownership is never spuriously lost. The only command that survived the bug was
the one that happened to land on a whole degree (66.0) — this suite makes every
command land on a whole degree.

This suite GUARDS the fix:
  1. Replays the real 09:28->09:53 ratchet sequence and asserts ownership is
     KEPT (baseline stays 73, no spurious relinquish, no re-engage).
  2. Sweeps worst_excess values that previously produced .5F commands and
     asserts every commanded value on BOTH axes is a whole degree.
  3. Proves a GENUINE user change is still detected (the fix did not blunt
     the existing user-change rule).
  4. Heating-direction symmetry (whole-degree heat commands too).
  5. Clamp bounds preserved (never above SETPOINT_NUDGE_MAX_F, never negative).

Same fake-hass pattern as tests/test_setpoint_nudge.py. Standalone script.
"""
import math
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

# This suite validates the setpoint-nudge STATE MACHINE's correctness in
# isolation (engage/deepen/release/readback logic) -- the mechanism itself
# is disabled in production (SETPOINT_NUDGE_ENABLED = False, 2026-09-02: on
# an ecobee that controls to the AVERAGE of 14 sensors, moving the whole-
# house setpoint to chase one chronically-hot room drags every OTHER room
# colder too -- see the smart-vent-controller skill). Force it on for this
# offline unit-test run so the mechanism keeps being exercised/kept honest
# for if/when a corrected, room-targeted redesign re-enables it.
svc.SETPOINT_NUDGE_ENABLED = True


# ---- fake HA backend ---------------------------------------------------------
class FakeHA(svc.SmartVentController):
    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=70.0, sp_heat=64.0):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 1, 8, 0, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
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
        self._nudge_persist_disable = True  # no disk writes in this offline suite
        self.sp_calls = []
        self.logs = []
        self._mode = mode
        self._hvac_mode = hvac_mode
        self._hvac_action = hvac_action
        self._sp_cool = sp_cool if sp_cool is not None else None
        self._sp_heat = sp_heat if sp_heat is not None else None
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
        # Cloud-truth setpoint sensors. Default to the mirror values so the
        # pre-existing suites (which treat the mirror as the live readback)
        # behave identically; a test that wants them to DIVERGE uses
        # set_cloud_truth(). Ownership decisions now follow THESE, not the
        # mirror, so a suite must keep them in sync unless it is deliberately
        # exercising the mirror-vs-cloud disagreement.
        self.states[svc.SETPOINT_TRUTH_COOL] = self._sp_cool
        self.states[svc.SETPOINT_TRUTH_HEAT] = self._sp_heat

    def live_cool(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"]

    def live_heat(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_low"]

    def set_cloud_truth(self, cool=None, heat=None, **dummy):
        """Set ONLY the cloud-truth setpoint sensors (leave the mirror alone).

        This is how a test makes the mirror and cloud truth DISAGREE. Values
        may be numeric, None, 'unknown', or 'unavailable'.
        """
        if cool is not None:
            self.states[svc.SETPOINT_TRUTH_COOL] = cool
        if heat is not None:
            self.states[svc.SETPOINT_TRUTH_HEAT] = heat

    def set_room_temp(self, zone, room, temp):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["temp"]] = float(temp)

    def occupy(self, zone, room):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["occupancy"]] = "on"

    def set_live_setpoints(self, cool=None, heat=None):
        a = self.attrs[(svc.THERMOSTAT, "all")]["attributes"]
        if cool is not None:
            a["target_temp_high"] = float(cool)
        if heat is not None:
            a["target_temp_low"] = float(heat)
        self.set_cloud_truth(cool=cool, heat=heat)

    def set_hvac_action(self, action):
        a = self.attrs[(svc.THERMOSTAT, "all")]["attributes"]
        a["hvac_action"] = action
        self._hvac_action = action

    def run_nudge(self):
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat, self._mode)


# ---- helpers -----------------------------------------------------------------
def engaged_ha(sp_cool=72.0, sp_heat=66.0, worst_excess=None, **kw):
    """OCCUPIED cooling Game Room that will engage a nudge for the given excess."""
    ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
                sp_cool=sp_cool, sp_heat=sp_heat, **kw)
    ha.occupy("upstairs", "Game Room")
    w = worst_excess if worst_excess is not None else 3.35
    ha.set_room_temp("upstairs", "Game Room",
                     sp_cool + svc.PRIORITY_MARGIN_BASE + w)
    return ha


def nudge_amount(w):
    """Mirror the controller's quantize-DOWN clamp exactly."""
    v = max(0.0, min(w * svc.SETPOINT_NUDGE_GAIN, svc.SETPOINT_NUDGE_MAX_F))
    return math.floor(v / svc.SETPOINT_NUDGE_STEP_F) * svc.SETPOINT_NUDGE_STEP_F


def is_whole(v):
    return v is not None and float(v).is_integer()


def setpoint_calls(ha):
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/resume_top_event"]


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


# =============================================================================
# 1. THE RATCHET REGRESSION GUARD (most important): replay the REAL 09:28 ->
#    09:53 sequence. The user's TRUE scheduled baseline was cool=73 heat=64.
#    At worst_excess 3.35 the OLD code commanded 71.5 (half-degree) -> readback
#    71 -> false "user changed" -> adopt 71 -> nudge again. THE FIX must command
#    a WHOLE degree, and the readback of that exact whole degree must KEEP
#    ownership past the confirm window with the baseline intact.
# =============================================================================
ha = engaged_ha(sp_cool=73.0, sp_heat=64.0, worst_excess=3.35)
ha.run_nudge()  # engage
writes1 = setpoint_calls(ha)
check("R1 engage: exactly ONE set_hold_temperature call", len(writes1) == 1)
if writes1:
    kw = writes1[0]
    check("R1 commanded cool is a WHOLE degree (was 71.5 before quantization)",
          is_whole(kw["cool_temp_f"]) and kw["cool_temp_f"] == 71.0)
    check("R1 commanded heat is a WHOLE degree (64.0)", is_whole(kw["heat_temp_f"]))
    check("R1 both axes whole", is_whole(kw["cool_temp_f"]) and is_whole(kw["heat_temp_f"]))
    check("R1 commanded cool == baseline - nudge(3.35) == 71.0",
          kw["cool_temp_f"] == 73.0 - nudge_amount(3.35))
check("R1 _sp_owned True", ha._sp_owned is True)
check("R1 baseline cool captured as the true 73.0", ha._sp_baseline_cool == 73.0)

# Thermostat reports back EXACTLY our (whole-degree) commanded value — the same
# whole degree the real ecobee would have echoed, which is precisely what never
# happened under the old 0.5F commands.
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.run_nudge()  # readback matches -> no mismatch recorded
check("R1 readback of exact whole degree: no mismatch recorded",
      ha._sp_mismatch_since is None)
check("R1 readback of exact whole degree: still owned", ha._sp_owned is True)

# Advance far past the confirm window (would have triggered the false
# relinquish in the bug: 09:28 -> 09:38 is ~10 min > 420s). Ownership must be
# KEPT and the baseline must STILL be 73.
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
n_logs = len(ha.logs)
ha.run_nudge()
check("R1 past confirm window: STILL owned (no false relinquish)", ha._sp_owned is True)
check("R1 past confirm window: baseline STILL 73.0 (no ratchet)",
      ha._sp_baseline_cool == 73.0)
check("R1 past confirm window: NO 'user changed setpoint' log emitted",
      not any("user changed setpoint" in m for m in ha.logs[n_logs:]))
check("R1 past confirm window: NO resume_top_event (ownership never dropped)",
      len(resume_calls(ha)) == 0)
check("R1 past confirm window: NO re-engage write (ownership held)",
      len(setpoint_calls(ha)) == 1)
check("R1 commanded setpoint still whole after the window", is_whole(ha.live_cool()))

# =============================================================================
# 2. EVERY commanded value on BOTH axes is a WHOLE degree across a range of
#    worst_excess inputs — sweeping values that the old 0.5F step produced as
#    .5 commands (e.g. those yielding 71.5 and 68.5). With STEP=1.0 and a
#    whole-degree baseline, every command lands on a whole degree, cooling AND
#    heating.
# =============================================================================
_cool_sweep = [3.35, 3.5, 5.84, 7.71, 2.5, 2.0, 4.0, 6.0, 3.0, 5.0, 1.9, 2.9]
_any_nonwhole = False
for _w in _cool_sweep:
    h = engaged_ha(sp_cool=73.0, sp_heat=64.0, worst_excess=_w)
    h.run_nudge()
    wr = setpoint_calls(h)
    if not wr:
        # If the excess is below the engage threshold (<1.5) or idle, no write;
        # skip (a value just under ENGAGE at 2.0+ always engages once > 1.5).
        check(f"R2 sweep w={_w}: engaged", len(wr) == 1)
        if not wr:
            _any_nonwhole = True
        continue
    kw = wr[0]
    if not (is_whole(kw["cool_temp_f"]) and is_whole(kw["heat_temp_f"])):
        _any_nonwhole = True
check("R2 ALL cooling-sweep commanded values (both axes) are whole degrees",
      not _any_nonwhole)

_heat_sweep = [3.35, 3.5, 5.5, 2.5, 4.0, 6.5, 3.0, 5.0, 2.0, 7.0]
_heat_nonwhole = False
for _w in _heat_sweep:
    h = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
               sp_cool=80.0, sp_heat=72.0)
    h.occupy("upstairs", "Game Room")
    h.set_room_temp("upstairs", "Game Room", 72.0 - 1.5 - _w)
    h._set_thermostat()
    h.run_nudge()
    wr = setpoint_calls(h)
    if not wr:
        check(f"R2 heat sweep w={_w}: engaged", len(wr) == 1)
        continue
    kw = wr[0]
    if not (is_whole(kw["heat_temp_f"]) and is_whole(kw["cool_temp_f"])):
        _heat_nonwhole = True
check("R2 ALL heating-sweep commanded values (both axes) are whole degrees",
      not _heat_nonwhole)

# =============================================================================
# 3. A GENUINE USER CHANGE is STILL detected. The user sets cool 74 while the
#    app commanded 71 -> readback differs by 3.0F -> relinquish fires and the
#    user's value is adopted (owned False, live stays 74). This proves the
#    whole-degree fix did NOT blunt the existing user-change detection rule.
# =============================================================================
ha = engaged_ha(sp_cool=72.0, sp_heat=66.0, worst_excess=2.5)  # nudge 2.0 -> cool 70
ha.run_nudge()  # engage, commanded cool 70 (whole)
check("R3 genuine-change setup: commanded cool 70 (whole)",
      is_whole(ha._sp_commanded_cool) and ha._sp_commanded_cool == 70.0)
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.run_nudge()  # our hold echoes back, matches
check("R3 genuine-change setup: still owned after echo", ha._sp_owned is True)
# The USER sets 74 (their own real change, 4.0F above our commanded 70).
ha.set_live_setpoints(cool=74.0, heat=66.0)
ha.run_nudge()  # fresh mismatch -> set _sp_mismatch_since, no action yet
check("R3 fresh user change: mismatch recorded, not yet relinquished",
      ha._sp_mismatch_since is not None and ha._sp_owned is True)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # mismatch persisted past confirm -> relinquish
check("R3 genuine user change detected: _sp_owned False (relinquished)",
      ha._sp_owned is False)
check("R3 genuine user change: ZERO resume_top_event (never pop user hold)",
      len(resume_calls(ha)) == 0)
check("R3 user's value ADOPTED: live cool is 74 (not our old commanded 70)",
      ha.live_cool() == 74.0)
check("R3 relinquish did NOT restore/ratchet the old baseline (owned False)",
      ha._sp_baseline_cool is None)

# =============================================================================
# 4. HEATING-DIRECTION SYMMETRY: commanded heat setpoints (and the coupled cool
#    axis) are whole degrees too. Baseline heat 72, excess 5.5 -> nudge 2.0
#    (MAX_F cap) -> heat 74 (whole); cool axis raises only if needed for the
#    6F gap -> 80.
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="heating", sp_cool=80.0, sp_heat=72.0)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 72.0 - 1.5 - 5.5)  # excess 5.5
ha._set_thermostat()
ha.run_nudge()
wr = setpoint_calls(ha)
check("R4 heat engage: exactly one write", len(wr) == 1)
if wr:
    kw = wr[0]
    check("R4 commanded heat is a WHOLE degree == baseline + nudge(5.5)",
          is_whole(kw["heat_temp_f"]) and kw["heat_temp_f"] == 72.0 + nudge_amount(5.5))
    check("R4 commanded heat == 74.0", kw["heat_temp_f"] == 74.0)
    check("R4 commanded cool is a WHOLE degree (coupled axis)", is_whole(kw["cool_temp_f"]))
    check("R4 gap preserved (cool - heat >= 6F)",
          kw["cool_temp_f"] - kw["heat_temp_f"] >= svc.SETPOINT_HEATCOOL_MIN_DELTA_F)

# =============================================================================
# 5. CLAMP BOUNDS PRESERVED: nudge never exceeds SETPOINT_NUDGE_MAX_F, never
#    negative — even for an absurd worst_excess where the old clamp would have
#    ratcheted the house way down.
# =============================================================================
ha = engaged_ha(sp_cool=73.0, sp_heat=64.0, worst_excess=200.0)
ha.run_nudge()
wr = setpoint_calls(ha)
check("R5 clamp: exactly one write at huge excess", len(wr) == 1)
if wr:
    kw = wr[0]
    nudge_used = 73.0 - kw["cool_temp_f"]
    check("R5 nudge_amount(200) is clamped to MAX", nudge_used == svc.SETPOINT_NUDGE_MAX_F)
    check("R5 commanded cool never below baseline - MAX",
          kw["cool_temp_f"] >= 73.0 - svc.SETPOINT_NUDGE_MAX_F)
    check("R5 commanded cool is a whole degree", is_whole(kw["cool_temp_f"]))
    check("R5 nudge is never negative", nudge_used >= 0.0)
# floor(min(200*2.0, 2.0)/1.0)*1.0 = 2.0, and the MAX clamp keeps it at 2.0.
check("R5 nudge_amount(w) is always a whole, non-negative number",
      all(is_whole(nudge_amount(x)) and nudge_amount(x) >= 0.0
          for x in [0.0, 0.5, 1.0, 1.5, 2.05, 3.0, 5.84, 7.71, 20.0, 200.0]))
# Minimum effective nudge is now 2.0F (a 0.5F or 1.0F nudge is unrepresentable;
# with GAIN=2.0 + MAX_F=2.0 the nudge is a single fixed 2.0F step that engages
# for ANY excess >= 1.0 — nudge = floor(min(w*2.0, 2.0)/1.0), so w must clear
# 0.5 for a 1.0F sub-quantum nudge and w>=1.0 for the full 2.0F cap; anything
# below 0.5 is 0.0F).
check("R5 minimum effective nudge is 2.0F (1.0F is now sub-quantum)",
      nudge_amount(1.0) == 2.0 and nudge_amount(0.5) == 1.0
      and nudge_amount(0.49) == 0.0)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
