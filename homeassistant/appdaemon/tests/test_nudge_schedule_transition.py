"""Offline validation of the SCHEDULE-TRANSITION CARVE-OUT for the setpoint
nudge's confirmed-mismatch (readback) relinquish path.

THE BUG (live-verified, 2026-09-03, Edgewater Road ecobee): the nudge writes
its cool/heat hold as holdType=nextTransition -- a deliberate dead-man's
switch that a crashed app can never leave stuck indefinitely. BY DESIGN that
hold is popped by the ecobee's OWN program engine at the next scheduled
transition. At local midnight the program advances climate home -> sleep;
both climates happen to share identical setpoints (heat 64.0 / cool 72.0), so
the *program* value doesn't move -- what moves is that OUR OWN HOLD evaporates
and the live setpoint snaps 70.0 -> 72.0. The pre-existing readback-mismatch
logic cannot tell that apart from a human turning the dial, so it declares a
CONFIRMED HUMAN OVERRIDE and latches a 120-minute cooldown plus suppresses
overnight pre-cool for the whole night -- for a change nobody made. This
happens every night and eats the first ~2h of the 01:00-06:30 pre-cool window.

The real house timeline that root-caused this (all three sensors come from
the SAME 180s coordinator poll, moved within 38ms of each other):

    05:00:58.012445Z  sensor.ecobee_edgewater_road_desired_cool      70.0 -> 72.0
    05:00:58.048630Z  sensor.ecobee_edgewater_road_schedule_status   hold -> following_schedule
    05:00:58.050440Z  sensor.ecobee_edgewater_road_current_climate   home -> sleep
    05:09:07Z         app latched override cooldown (489s later = CONFIRM_SEC 420
                       + one ~69s control tick)

THE FIX: `_mismatch_is_schedule_transition()` looks for positive, multi-signal
evidence that this is our own hold expiring rather than a human override:
schedule_status == 'following_schedule' (a human action instead flips it to
'hold'), current_climate is a real, fresh value (current_climate changes ONLY
when the ecobee's program engine itself advances), and all three sensors'
`last_changed` (schedule_status, current_climate, and the ACTIVE-axis cloud
truth setpoint) land within SCHEDULE_TRANSITION_COINCIDENCE_SEC (300s) of each
other -- purely in the sensors' own UTC last_changed frame, never compared
against self.datetime(). Any missing/unknown/unavailable/unparseable signal,
or any exception, resolves to False -- 'never fight a human' stays absolute.

No pytest / appdaemon needed: same stub pattern as
tests/test_nudge_cloud_truth_readback.py.
"""
import sys
import types
from datetime import datetime, timedelta, timezone

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

svc.SETPOINT_NUDGE_ENABLED = True

GR = "Game Room"          # occupant-driving room (margin base 1.5, no override)
GR_KEY = ("upstairs", GR)
_SENTINEL = object()


class FakeHA(svc.SmartVentController):
    """Cloud-truth thermostat fake extended with a `last_changed` store and
    the two new schedule sensors, so the coincidence math can be exercised
    directly."""

    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=70.0, sp_heat=64.0):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 3, 5, 0, 0)
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
        self._sp_truth_unavailable_logged = False
        self._sp_override_cooldown_until = None
        self._precool_suppressed_window_id = None
        self._nudge_persist_disable = True
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
        self.states.setdefault(svc.SETPOINT_TRUTH_COOL, self._sp_cool)
        self.states.setdefault(svc.SETPOINT_TRUTH_HEAT, self._sp_heat)

    def live_cool(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"]

    def live_heat(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_low"]

    def set_cloud_truth(self, cool=_SENTINEL, heat=_SENTINEL, **dummy):
        if cool is not _SENTINEL:
            self.states[svc.SETPOINT_TRUTH_COOL] = cool
        if heat is not _SENTINEL:
            self.states[svc.SETPOINT_TRUTH_HEAT] = heat
        self._sp_truth_unavailable_logged = False

    def set_room_temp(self, zone, room, temp):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["temp"]] = float(temp)

    def occupy(self, zone, room):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["occupancy"]] = "on"

    # ---- schedule sensors + last_changed -------------------------------------
    def set_last_changed(self, entity, dt_or_str):
        self.attrs[(entity, "last_changed")] = dt_or_str

    def set_schedule(self, schedule_status=_SENTINEL, current_climate=_SENTINEL):
        if schedule_status is not _SENTINEL:
            self.states[svc.SCHEDULE_STATUS_ENTITY] = schedule_status
        if current_climate is not _SENTINEL:
            self.states[svc.CURRENT_CLIMATE_ENTITY] = current_climate

    # ---- nudge driver ----------------------------------------------------------
    def run_nudge(self):
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat, self._mode)


def setpoint_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/resume_top_event"]


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


def make_owned_cooling_ha(commanded_cool=70.0, commanded_heat=64.0,
                           baseline_cool=72.0, baseline_heat=66.0):
    """A HA already OWNED on the cool axis with a mismatch already recorded
    at the confirm boundary, ready to have schedule/climate sensors set and
    then be pushed past CONFIRM_SEC."""
    ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
                sp_cool=baseline_cool, sp_heat=baseline_heat)
    ha.occupy(*GR_KEY)
    ha.set_room_temp("upstairs", GR, baseline_cool + 1.5 + 6.5)
    ha.run_nudge()  # engage
    assert ha._sp_owned is True
    ha._sp_commanded_cool = commanded_cool
    ha._sp_commanded_heat = commanded_heat
    ha._sp_baseline_cool = baseline_cool
    ha._sp_baseline_heat = baseline_heat
    ha._sp_heating = False
    return ha


# =============================================================================
# 1. SCHEDULE CASE (RED-GREEN): all three sensors coincident within 1s ->
#    clean relinquish, NO cooldown, NO pre-cool suppression.
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, 12445, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)  # snapped back to schedule value
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts + timedelta(milliseconds=36))
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts + timedelta(milliseconds=38))
ha.run_nudge()  # fresh mismatch -> just records _sp_mismatch_since
check("A1 fresh mismatch: still owned (confirm window)", ha._sp_owned is True)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # confirmed -> schedule-driven relinquish
check("A1 SCHEDULE relinquish: cooldown NOT latched",
      ha._sp_override_cooldown_until is None)
check("A1 SCHEDULE relinquish: precool NOT suppressed",
      ha._precool_suppressed_window_id is None)
check("A1 SCHEDULE relinquish: _sp_owned False", ha._sp_owned is False)
check("A1 SCHEDULE relinquish: _sp_commanded_cool cleared",
      ha._sp_commanded_cool is None)
check("A1 SCHEDULE relinquish: _sp_mismatch_since cleared",
      ha._sp_mismatch_since is None)

# =============================================================================
# 2. HUMAN CASE (hold): identical timestamps but schedule_status='hold' ->
#    cooldown IS latched.
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, 12445, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="hold", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts + timedelta(milliseconds=36))
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts + timedelta(milliseconds=38))
ha.run_nudge()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("A2 HUMAN(hold) case: cooldown IS latched",
      ha._sp_override_cooldown_until == ha.datetime() +
      timedelta(minutes=svc.SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN))
check("A2 HUMAN(hold) case: precool IS-suppressible path taken (owned False)",
      ha._sp_owned is False)

# =============================================================================
# 3. HUMAN CASE (not coincident): following_schedule + fresh current_climate,
#    but current_climate.last_changed is 3600s away from truth -> cooldown latched.
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts + timedelta(seconds=1))
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts + timedelta(seconds=3600))
ha.run_nudge()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("A3 not-coincident timestamps: cooldown IS latched",
      ha._sp_override_cooldown_until is not None)

# =============================================================================
# 4. UNAVAILABLE current_climate (and 'unknown') -> cooldown latched.
# =============================================================================
for bad in ("unavailable", "unknown"):
    ha = make_owned_cooling_ha()
    truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
    ha.set_cloud_truth(cool=72.0, heat=64.0)
    ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
    ha.set_schedule(schedule_status="following_schedule", current_climate=bad)
    ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
    ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
    ha.run_nudge()
    ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
    ha.run_nudge()
    check(f"A4[{bad}] current_climate {bad!r}: cooldown IS latched",
          ha._sp_override_cooldown_until is not None)

# =============================================================================
# 5. MISSING SENSOR: get_state returns None for current_climate -> cooldown latched.
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="following_schedule")  # current_climate never set -> None
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha.run_nudge()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("A5 missing current_climate sensor: cooldown IS latched",
      ha._sp_override_cooldown_until is not None)

# =============================================================================
# 6. UNPARSEABLE TIMESTAMP: cooldown latched AND no exception escapes.
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, "not-a-timestamp")
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
raised = False
try:
    ha.run_nudge()
    ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
    ha.run_nudge()
except Exception:
    raised = True
check("A6 unparseable timestamp: no exception escaped", raised is False)
check("A6 unparseable timestamp: cooldown IS latched",
      ha._sp_override_cooldown_until is not None)

# =============================================================================
# 7. RE-ENGAGE: immediately after schedule-driven relinquish, next cycle with
#    worst_excess still above ENGAGE_F writes a NEW hold (RED-GREEN).
# =============================================================================
ha = make_owned_cooling_ha()
truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
# room still hot against the NEW baseline (72) so re-engage should fire
ha.set_room_temp("upstairs", GR, 72.0 + 1.5 + 6.5)
ha.run_nudge()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # schedule-driven relinquish; no cooldown
n_calls_before = len(setpoint_calls(ha))
ha.advance(1)
ha.run_nudge()  # next cycle: should RE-ENGAGE (no cooldown blocking it)
check("A7 RE-ENGAGE: a new set_hold call appears after relinquish",
      len(setpoint_calls(ha)) > n_calls_before)
check("A7 RE-ENGAGE: new baseline is 72.0 (the schedule's post-transition value)",
      ha._sp_baseline_cool == 72.0)

# =============================================================================
# 8. PRE-COOL: (a) schedule-driven relinquish inside the window does NOT set
#    _precool_suppressed_window_id; (b) human-driven relinquish inside the
#    window DOES set it (RED-GREEN on 8a).
# =============================================================================
def precool_window_datetime():
    # find a time inside the overnight pre-cool window using the app's own
    # window-active predicate, starting from a plausible early-morning hour.
    for hour in (1, 2, 3, 4, 5):
        candidate = datetime(2026, 9, 3, hour, 0, 0)
        probe = FakeHA()
        probe._clock = candidate
        if probe._precool_window_active(candidate):
            return candidate
    return None

window_dt = precool_window_datetime()
check("A8 setup: found a time inside the pre-cool window", window_dt is not None)

if window_dt is not None:
    # 8a: schedule-driven relinquish inside the window.
    ha = make_owned_cooling_ha()
    ha._clock = window_dt
    truth_ts = window_dt.replace(tzinfo=timezone.utc)
    ha.set_cloud_truth(cool=72.0, heat=64.0)
    ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
    ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
    ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
    ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
    ha.run_nudge()
    ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
    ha.run_nudge()
    check("A8a schedule-driven relinquish in-window: precool NOT suppressed",
          ha._precool_suppressed_window_id is None)

    # 8b: human-driven relinquish inside the window.
    ha = make_owned_cooling_ha()
    ha._clock = window_dt
    truth_ts = window_dt.replace(tzinfo=timezone.utc)
    ha.set_cloud_truth(cool=72.0, heat=64.0)
    ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
    ha.set_schedule(schedule_status="hold", current_climate="sleep")
    ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
    ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
    ha.run_nudge()
    ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
    ha.run_nudge()
    check("A8b human-driven relinquish in-window: precool IS suppressed",
          ha._precool_suppressed_window_id is not None)

# =============================================================================
# 9. HEATING AXIS: with self._sp_heating = True, the carve-out reads
#    desired_heat's last_changed (not desired_cool's).
# =============================================================================
# 9a: desired_cool stale/far, desired_heat coincident -> carve-out STILL fires.
ha = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
            sp_cool=72.0, sp_heat=64.0)
ha.occupy(*GR_KEY)
ha._sp_owned = True
ha._sp_commanded_cool = 72.0
ha._sp_commanded_heat = 66.0
ha._sp_baseline_cool = 72.0
ha._sp_baseline_heat = 64.0
ha._sp_heating = True
truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)  # heat snapped back to schedule value
ha.set_last_changed(svc.SETPOINT_TRUTH_HEAT, truth_ts)                    # coincident
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts + timedelta(hours=5))  # stale/far
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
ha._sp_mismatch_since = ha.datetime() - timedelta(seconds=svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
result_9a = ha._mismatch_is_schedule_transition()
check("A9a heating axis: carve-out fires off desired_heat (cool axis ignored)",
      result_9a is True)

# 9b: mirror case - desired_heat stale/far -> cooldown-path (carve-out does NOT fire).
ha2 = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
             sp_cool=72.0, sp_heat=64.0)
ha2.occupy(*GR_KEY)
ha2._sp_owned = True
ha2._sp_commanded_cool = 72.0
ha2._sp_commanded_heat = 66.0
ha2._sp_baseline_cool = 72.0
ha2._sp_baseline_heat = 64.0
ha2._sp_heating = True
ha2.set_cloud_truth(cool=72.0, heat=64.0)
ha2.set_last_changed(svc.SETPOINT_TRUTH_HEAT, truth_ts + timedelta(hours=5))  # stale/far
ha2.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)                        # irrelevant axis
ha2.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha2.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha2.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
result_9b = ha2._mismatch_is_schedule_transition()
check("A9b heating axis: desired_heat stale -> carve-out does NOT fire",
      result_9b is False)

# =============================================================================
# 10. PERSISTENCE: after a schedule-driven relinquish the persisted record has
#     owned=False, override_cooldown_until null/absent, and version == 1.
# =============================================================================
import json
import os
import tempfile

ha = make_owned_cooling_ha()
ha._nudge_persist_disable = False  # enable real file I/O for this assertion
tmpdir = tempfile.mkdtemp()
statepath = os.path.join(tmpdir, "nudge_state.json")
ha._nudge_state_path = lambda: statepath

truth_ts = datetime(2026, 9, 3, 5, 0, 58, tzinfo=timezone.utc)
ha.set_cloud_truth(cool=72.0, heat=64.0)
ha.set_last_changed(svc.SETPOINT_TRUTH_COOL, truth_ts)
ha.set_schedule(schedule_status="following_schedule", current_climate="sleep")
ha.set_last_changed(svc.SCHEDULE_STATUS_ENTITY, truth_ts)
ha.set_last_changed(svc.CURRENT_CLIMATE_ENTITY, truth_ts)
ha.run_nudge()
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # schedule-driven relinquish, real persist write

check("A10 persistence: state file was written", os.path.exists(statepath))
if os.path.exists(statepath):
    with open(statepath) as f:
        record = json.load(f)
    check("A10 persistence: owned is False", record.get("owned") is False)
    check("A10 persistence: override_cooldown_until is null/absent",
          record.get("override_cooldown_until") in (None,))
    check("A10 persistence: version == 1", record.get("version") == 1)
else:
    check("A10 persistence: owned is False", False)
    check("A10 persistence: override_cooldown_until is null/absent", False)
    check("A10 persistence: version == 1", False)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
