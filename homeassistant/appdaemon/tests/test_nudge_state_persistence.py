"""Offline validation of setpoint-nudge ownership persistence + validated restore.

Covers the 2026-09-01 restart-amnesia / baseline-ratchet fix. The ratchet:
  2026-09-01 13:03:55 INFO smart_vent_controller:   SETPOINT-NUDGE: engaged (cool)
  worst_excess 10.86F, nudge to cool 63.0F heat 57.0F (baseline cool 66.0 heat 60.0)
The thermostat read 66/60 at that moment ONLY because a PREVIOUS incarnation of
this same app had nudged it down from the user's true 72F baseline; the restarted
app had no memory of that, so it captured its own leftover nudge (66) as if it
were the user's setpoint and nudged 3F further to 63. Every restart during an
active nudge ratchets: 72 -> 66 -> 63 -> ...

Fix: persist the full nudge-ownership record (as ONE atomic JSON file, written
BEFORE the setHold service call on every engage/deepen/relinquish/release
transition) and on restore RE-ADOPT ownership ONLY when the live readback
corroborates the persisted record. On ANY mismatch/expiry/corruption the record
is DISCARDED silently and today's existing behavior (adopt the live value as the
user's baseline) runs. NO release/resume call is ever issued on the mismatch
path — that would clobber a genuine user hold.

No pytest / appdaemon needed (same stub pattern as the other suites). State-file
I/O is pointed at a temp dir so tests never touch a real state file.
"""
import json
import os
import sys
import tempfile
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

APP_DIR = tempfile.mkdtemp(prefix="nudge_state_test_")


# ---- fake HA backend (mirrors test_setpoint_nudge, + persistence wiring) -----
class FakeHA(svc.SmartVentController):
    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=70.0, sp_heat=64.0, tmp=None):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 1, 18, 0, 0)
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
        self._nudge_persist_disable = False
        self._nudge_restore_pending = False
        self._nudge_state_file = os.path.join(tmp or APP_DIR,
                                              svc.NUDGE_STATE_FILENAME)
        self.sp_calls = []
        self.logs = []
        self.order = []          # instrumentation: ("persist",) / ("service", svc)
        self.persist_count = 0
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
        self.order.append(("service", service))
        self.sp_calls.append((service, kwargs))

    # ---- persistence write instrumentation (ordering + per-transition) -------
    # WRITE-AHEAD ordering: the state file must be written BEFORE the setHold
    # service call. Track both on the shared self.order list so a test can assert
    # persist-before-service explicitly.
    def _persist_nudge_state(self, *args, **kwargs):
        self.persist_count += 1
        self.order.append(("persist",))
        return super()._persist_nudge_state(*args, **kwargs)

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
        """Set ONLY the cloud-truth setpoint sensors (leave the mirror alone)."""
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


# ---- persistence-oriented helpers ---------------------------------------------
def engaged_ha(sp_cool=72.0, sp_heat=66.0, worst_excess=5.5, tmp=None, **kw):
    """An OCCUPIED cooling thermostat at a hot Game Room that will engage a nudge."""
    ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
                sp_cool=sp_cool, sp_heat=sp_heat, tmp=tmp, **kw)
    ha.occupy("upstairs", "Game Room")
    ha.set_room_temp("upstairs", "Game Room",
                     sp_cool + svc.PRIORITY_MARGIN_BASE + worst_excess)
    return ha


def state_record(**fields):
    """Build a valid persisted record dict (defaults to a "we hold 66, baseline 72"
    cooling nudge commanded at the instance clock 'now')."""
    rec = {
        "version": svc.NUDGE_STATE_VERSION,
        "owned": True,
        "commanded_cool": 66.0,
        "commanded_heat": 60.0,
        "baseline_cool": 72.0,
        "baseline_heat": 66.0,
        "heating": False,
    }
    rec.update(fields)
    return rec


def write_state_file(ha, record):
    with open(ha._nudge_state_file, "w") as f:
        f.write(json.dumps(record))


def restore_and_first_cycle(ha):
    """Mirror initialize() + the first control_loop cycle exactly: load the
    record, then validate it against the CURRENT live readback."""
    ha._restore_nudge_ownership()
    mode, action, tcool, theat = ha._get_thermostat_state()
    if ha._nudge_restore_pending:
        ha._nudge_restore_pending = False
        ha._validate_restored_nudge(tcool, theat)


def setpoint_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    return [kw for s, kw in ha.sp_calls
            if s == "ecobee_enhanced/resume_top_event"]


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


def _rm(tmp):
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
# 1. THE RATCHET REGRESSION GUARD (most important).
#    baseline 72 -> app nudges to 66 -> app 'restarts' with thermostat still
#    reading 66 -> must RE-ADOPT ownership with baseline 72, must NOT capture 66
#    as a new baseline, must NOT nudge to 63.
# =============================================================================
tmp = tempfile.mkdtemp()
# Simulate the previous incarnation having engaged (baseline 72 -> commanded 66).
ha = engaged_ha(sp_cool=72.0, sp_heat=66.0, tmp=tmp)
ha.set_live_setpoints(cool=66.0, heat=60.0)   # thermostat still reading the hold
write_state_file(ha, state_record(commanded_at=ha.datetime().strftime(
    "%Y-%m-%dT%H:%M:%SZ")))
# 'Restart': fresh instance with the same temp state file and live readback 66.
ha2 = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
             sp_cool=66.0, sp_heat=60.0, tmp=tmp)
# Game Room at excess ~1.0 vs the LIVE 66 (hysteresis band: no release, no deepen)
ha2.occupy("upstairs", "Game Room")
ha2.set_room_temp("upstairs", "Game Room", 66.0 + svc.PRIORITY_MARGIN_BASE + 1.0)
ha2._set_thermostat()
restore_and_first_cycle(ha2)
check("R1 restart: ownership RE-ADOPTED (readback matches commanded 66)",
      ha2._sp_owned is True)
check("R1 restart: baseline kept at USER's 72 (NOT captured 66)",
      ha2._sp_baseline_cool == 72.0)
ha2.run_nudge()
check("R1 restart: does NOT nudge to 63 (reads 66 as ITS OWN hold)",
      ha2._sp_commanded_cool == 66.0 and len(setpoint_calls(ha2)) == 0)
_rm(tmp)

# =============================================================================
# 2. WRITE-AHEAD ORDERING: state file is written BEFORE the setHold service call.
# =============================================================================
tmp = tempfile.mkdtemp()
ha = engaged_ha(sp_cool=72.0, sp_heat=66.0, tmp=tmp, worst_excess=5.5)
ha.run_nudge()  # engage
pi = [i for i, e in enumerate(ha.order) if e[0] == "persist"]
si = [i for i, e in enumerate(ha.order)
      if e == ("service", "ecobee_enhanced/set_hold_temperature")]
check("A write-ahead: persist event index < setHold service index",
      bool(pi) and bool(si) and pi[0] < si[0])
# And the file content already reflects the intended command at persist time.
with open(ha._nudge_state_file) as f:
    rec = json.load(f)
check("A write-ahead: file already carries the commanded cool",
      abs(rec["commanded_cool"] - ha._sp_commanded_cool) < 1e-9)
check("A write-ahead: file carries owned=True", rec["owned"] is True)
_rm(tmp)

# =============================================================================
# 3. RESTORE with readback matching commanded -> ownership re-adopted, baseline
#    preserved.
# =============================================================================
tmp = tempfile.mkdtemp()
write_state_file(FakeHA(tmp=tmp), state_record(commanded_at="2026-09-01T18:00:00Z"))
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=66.0, sp_heat=60.0, tmp=tmp)  # live == commanded 66
restore_and_first_cycle(ha)
check("B restore-match: ownership re-adopted", ha._sp_owned is True)
check("B restore-match: baseline preserved (72/66)",
      ha._sp_baseline_cool == 72.0 and ha._sp_baseline_heat == 66.0)
check("B restore-match: commanded preserved (66/60)",
      ha._sp_commanded_cool == 66.0 and ha._sp_commanded_heat == 60.0)
_rm(tmp)

# =============================================================================
# 4. RESTORE with readback NOT matching + confirm window EXPIRED -> discarded,
#    live adopted as baseline, NO release/resume service call.
# =============================================================================
tmp = tempfile.mkdtemp()
old = (datetime(2026, 9, 1, 18, 0, 0) - timedelta(
    seconds=svc.SETPOINT_NUDGE_CONFIRM_SEC + 30)).strftime("%Y-%m-%dT%H:%M:%SZ")
write_state_file(FakeHA(tmp=tmp), state_record(commanded_at=old))
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=69.0, sp_heat=63.0, tmp=tmp)  # live differs from commanded 66
restore_and_first_cycle(ha)
check("C expired-mismatch: ownership discarded", ha._sp_owned is False)
check("C expired-mismatch: NO resume_top_event issued",
      len(resume_calls(ha)) == 0)
check("C expired-mismatch: live not touched (no set_hold back-fill)",
      len(setpoint_calls(ha)) == 0)
check("C expired-mismatch: baseline cleared (live 69 becomes future baseline)",
      ha._sp_baseline_cool is None)
_rm(tmp)

# =============================================================================
# 5. RESTORE with confirm window still OPEN -> re-adopt as in-flight.
#    readback still matches the PRIOR (baseline) value -> keep ownership.
# =============================================================================
tmp = tempfile.mkdtemp()
ha0 = FakeHA(hvac_mode="heat_cool", hvac_action="cooling", tmp=tmp)
now0 = ha0.datetime().strftime("%Y-%m-%dT%H:%M:%SZ")
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=72.0, sp_heat=66.0, tmp=tmp)  # live still == baseline (in-flight)
write_state_file(ha, state_record(commanded_at=now0))
restore_and_first_cycle(ha)
check("D in-flight: ownership re-adopted (window open)", ha._sp_owned is True)
check("D in-flight: baseline preserved", ha._sp_baseline_cool == 72.0)
_rm(tmp)

# =============================================================================
# 6. MISSING FILE -> clean fall-through, no crash.
# =============================================================================
tmp = tempfile.mkdtemp()
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=66.0, sp_heat=60.0, tmp=tmp)  # no file written
restore_and_first_cycle(ha)
check("E missing-file: no crash, ownership stays False", ha._sp_owned is False)
check("E missing-file: no service calls", len(ha.sp_calls) == 0)
check("E missing-file: no restore pending", ha._nudge_restore_pending is False)
_rm(tmp)

# =============================================================================
# 7. CORRUPT / UNPARSEABLE JSON -> discarded, no crash, no service call.
# =============================================================================
tmp = tempfile.mkdtemp()
with open(os.path.join(tmp, svc.NUDGE_STATE_FILENAME), "w") as f:
    f.write("{ this is not json !!!")
ha = FakeHA(tmp=tmp)
restore_and_first_cycle(ha)
check("F corrupt-json: no crash, ownership discarded", ha._sp_owned is False)
check("F corrupt-json: no service calls", len(ha.sp_calls) == 0)
# Also: valid JSON but wrong shape / missing fields -> discard.
write_state_file(FakeHA(tmp=tmp), {"owned": True, "version": 999})
ha2 = FakeHA(tmp=tmp)
restore_and_first_cycle(ha2)
check("F wrong-version: discarded", ha2._sp_owned is False)
_rm(tmp)

# =============================================================================
# 8. PERSIST FIRES ON EVERY TRANSITION: engage, (no deepen — impossible now),
#    relinquish, release.
# =============================================================================
tmp = tempfile.mkdtemp()
# --- engage ---
ha = engaged_ha(sp_cool=72.0, sp_heat=66.0, tmp=tmp, worst_excess=2.5)
ha.run_nudge()
pc_engage = ha.persist_count
check("G engage: persisted once", pc_engage == 1)
# --- would-be deepen --- (dwell elapses, room worsens while conditioning)
# 2026-09-02 redesign: GAIN=2.0 + MAX_F=2.0 saturate the instant the mechanism
# engages (GAIN * ENGAGE_F = 2.0*1.5 = 3.0 >= MAX_F=2.0), so the nudge collapses
# to a single fixed 2.0F value and the first engage already wrote the maximum
# possible. A would-be deepen cycle (room worsens, dwell elapsed) recomputes the
# SAME commanded value (nudge_amount(6.0) is still 2.0) and the deepen branch's
# own guard returns without writing — so it must NOT produce a second persist.
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.advance(svc.SETPOINT_NUDGE_DWELL_SEC + 1)
ha.set_room_temp("upstairs", "Game Room",
                 ha.live_cool() + svc.PRIORITY_MARGIN_BASE + 6.0)  # excess 6.0
ha.run_nudge()
check("G would-be deepen: NO second persist (single fixed cap, no ratchet)",
      ha.persist_count == 1 and ha._sp_commanded_cool == 70.0)
# --- release --- (room recovers -> resume_top_event, persist owned=False)
ha.set_live_setpoints(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)
ha.set_room_temp("upstairs", "Game Room",
                 ha.live_cool() + svc.PRIORITY_MARGIN_BASE + 0.2)  # excess 0.2
ha.set_hvac_action("cooling")
ha.run_nudge()
check("G release: persisted a relinquishment (total 2) + owned cleared",
      ha.persist_count == 2 and ha._sp_owned is False)
with open(ha._nudge_state_file) as f:
    rel = json.load(f)
check("G release: file records owned=False", rel["owned"] is False)
# --- relinquish (user override, confirmed) ---
ha = engaged_ha(sp_cool=72.0, sp_heat=66.0, tmp=tmp, worst_excess=2.5)
ha.run_nudge()  # engage (persist 1)
ha.set_live_setpoints(cool=ha.live_cool() + 2.0, heat=66.0)  # user change
ha.run_nudge()  # fresh mismatch -> no persist yet
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # confirmed -> relinquish (persist 2)
check("G relinquish: persisted and ownership cleared",
      ha.persist_count == 2 and ha._sp_owned is False)
with open(ha._nudge_state_file) as f:
    rel2 = json.load(f)
check("G relinquish: file records owned=False", rel2["owned"] is False)
_rm(tmp)

# =============================================================================
# 9. BOTH AXES persisted and restored together (heatCoolMinDelta pair integrity).
# =============================================================================
tmp = tempfile.mkdtemp()
# Heating nudge: OCCUPIED Game Room COLD (off_target = heat_sp - temp), hot
# excess 4.0 -> heat setpoint moves UP. Construct explicitly (engaged_ha is
# cooling-oriented).
ha = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
            sp_cool=75.0, sp_heat=70.0, tmp=tmp)
ha.occupy("upstairs", "Game Room")
ha.set_room_temp("upstairs", "Game Room", 64.5)  # excess = (70-64.5) - 1.5 = 4.0
ha._set_thermostat()
ha.run_nudge()
with open(ha._nudge_state_file) as f:
    rec = json.load(f)
check("H pair: heat-axis recorded", rec["heating"] is True
      and abs(rec["commanded_heat"] - ha._sp_commanded_heat) < 1e-9)
# 'Restart' with live == commanded; restore both axes together.
ha2 = FakeHA(hvac_mode="heat_cool", hvac_action="heating",
             sp_cool=rec["commanded_cool"], sp_heat=rec["commanded_heat"], tmp=tmp)
restore_and_first_cycle(ha2)
check("H pair: both axes restored together",
      ha2._sp_commanded_cool == rec["commanded_cool"]
      and ha2._sp_commanded_heat == rec["commanded_heat"]
      and ha2._sp_baseline_cool == 75.0 and ha2._sp_baseline_heat == 70.0)
check("H pair: ownership re-adopted", ha2._sp_owned is True)
# Half-record (missing one commanded axis) must be DISCARDED, never half-restored.
write_state_file(FakeHA(tmp=tmp), {
    "version": svc.NUDGE_STATE_VERSION, "owned": True,
    "commanded_cool": 66.0, "commanded_heat": None,
    "baseline_cool": 72.0, "baseline_heat": 66.0, "heating": False,
    "commanded_at": "2026-09-01T18:00:00Z"})
ha3 = FakeHA(tmp=tmp)
restore_and_first_cycle(ha3)
check("H half-record: discarded, not partially restored",
      ha3._sp_owned is False and ha3._sp_commanded_cool is None)
_rm(tmp)

# =============================================================================
# 10. A genuine USER change while the app was down is NOT clobbered: no release
#     issued; the user's value is adopted as the new baseline.
# =============================================================================
tmp = tempfile.mkdtemp()
old = (datetime(2026, 9, 1, 18, 0, 0) - timedelta(
    seconds=svc.SETPOINT_NUDGE_CONFIRM_SEC + 30)).strftime("%Y-%m-%dT%H:%M:%SZ")
# While the app was down the USER set the cool setpoint to 69 (from our 66).
write_state_file(FakeHA(tmp=tmp), state_record(commanded_at=old))
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=69.0, sp_heat=63.0, tmp=tmp)
restore_and_first_cycle(ha)
check("I user-change: NO resume/release issued (user hold untouched)",
      len(resume_calls(ha)) == 0)
check("I user-change: ownership discarded, live adopted as baseline",
      ha._sp_owned is False and ha._sp_baseline_cool is None)
ha.set_room_temp("upstairs", "Game Room",
                 69.0 + svc.PRIORITY_MARGIN_BASE + 5.5)
ha.occupy("upstairs", "Game Room")
ha.run_nudge()
# Next nudge is off the USER's 69 (NOT our stale 66) and never pops their hold.
check("I user-change: next engage is off the USER's live baseline (69 - nudge)",
      len(setpoint_calls(ha)) >= 1
      and abs(ha._sp_baseline_cool - 69.0) < 1e-9)
check("I user-change: still no resume issued",
      len(resume_calls(ha)) == 0)
_rm(tmp)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
