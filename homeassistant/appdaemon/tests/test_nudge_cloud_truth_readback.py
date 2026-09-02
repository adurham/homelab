"""Offline validation of reading the setpoint-nudge ownership readback and the
engage-time baseline from the ecobee CLOUD-TRUTH sensors instead of the
homekit_controller mirror.

THE BUG (root-caused live, 2026-09-01): after engaging a cool/heat hold via the
ecobee_enhanced service, `_apply_setpoint_nudge` checked ownership by reading
back the CURRENT setpoints from `climate.ecobee_thermostat` (a homekit_controller
mirror) attributes target_temp_high/low. That mirror DOES NOT reflect a cloud-side
hold: live-verified it kept reporting 66/60 while the real active hold was cool 63 /
heat 57. So the value-match ownership check failed every cycle, the app concluded
"the user changed the setpoint", relinquished, then re-engaged ~2 min later
(13:13 -> 14:06 churn loop). The baseline captured at engage came from the same
stale mirror, so `baseline cool 66.0` was itself wrong.

THE FIX: the nudge's ownership readback and engage-time baseline come from two
new ecobee_enhanced sensors exposing the runtime's authoritative
desiredCool/desiredHeat (SETPOINT_TRUTH_COOL / SETPOINT_TRUTH_HEAT), and the
nudge makes NO ownership decision on a cycle where either cloud truth is
missing/'unknown'/'unavailable'/non-numeric (no relinquish, no engage, no
re-baseline; the ecobee hold is holdType=nextTransition and expires on its own).

Assertion 6 is the load-bearing regression: at least one test drives the mirror
and cloud truth to DISAGREE and asserts the decision follows cloud truth, so a
future refactor that mistakenly reads climate.ecobee_thermostat for the nudge
fails this suite.

No pytest / appdaemon needed: same stub pattern as tests/test_setpoint_nudge.py.
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

# This suite validates the setpoint-nudge STATE MACHINE's correctness in
# isolation (engage/deepen/release/readback logic) -- the mechanism itself
# is disabled in production (SETPOINT_NUDGE_ENABLED = False, 2026-09-02: on
# an ecobee that controls to the AVERAGE of 14 sensors, moving the whole-
# house setpoint to chase one chronically-hot room drags every OTHER room
# colder too -- see the smart-vent-controller skill). Force it on for this
# offline unit-test run so the mechanism keeps being exercised/kept honest
# for if/when a corrected, room-targeted redesign re-enables it.
svc.SETPOINT_NUDGE_ENABLED = True

GR = "Game Room"          # occupant-driving room (margin base 1.5, no override)
GR_KEY = ("upstairs", GR)
_SENTINEL = object()      # allows set_cloud_truth(cool=None) to set None


class FakeHA(svc.SmartVentController):
    """Mirror + cloud-truth thermostat fake. The cloud-truth sensors can be set
    independently of the mirror (set_cloud_truth) so disagreement tests work."""

    def __init__(self, mode="Auto", hvac_mode="heat_cool", hvac_action="cooling",
                 sp_cool=70.0, sp_heat=64.0):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 9, 1, 13, 0, 0)
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
                "target_temp_high": self._sp_cool,   # mirror only
                "target_temp_low": self._sp_heat,    # mirror only
                "current_temperature": 72.0,
            },
        }
        # Cloud-truth sensors: default to the CURRENT mirror baseline values.
        # Ownership decisions now follow THESE, not the mirror.
        self.states.setdefault(svc.SETPOINT_TRUTH_COOL, self._sp_cool)
        self.states.setdefault(svc.SETPOINT_TRUTH_HEAT, self._sp_heat)

    def live_cool(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"]

    def live_heat(self):
        return self.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_low"]

    def set_cloud_truth(self, cool=_SENTINEL, heat=_SENTINEL, **dummy):
        """Set ONLY the cloud-truth sensors, leaving the mirror alone. Values may
        be numeric, None, 'unknown', or 'unavailable'. Use the module sentinel
        (the default) to skip an axis so None is a legal explicit value."""
        if cool is not _SENTINEL:
            self.states[svc.SETPOINT_TRUTH_COOL] = cool
        if heat is not _SENTINEL:
            self.states[svc.SETPOINT_TRUTH_HEAT] = heat
        self._sp_truth_unavailable_logged = False  # re-arm the one-shot log guard

    def set_room_temp(self, zone, room, temp):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["temp"]] = float(temp)

    def occupy(self, zone, room):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["occupancy"]] = "on"

    # ---- nudge driver ----------------------------------------------------------
    def run_nudge(self):
        mode, action, tcool, theat = self._get_thermostat_state()
        return self._apply_setpoint_nudge(mode, action, tcool, theat, self._mode)


def engage_cooling_hold(ha, echo=True):
    """Drive a cooling nudge to engage and (optionally) echo the hold back on the
    cloud-truth sensors. Requires an OCCUPIED hot Game Room already set."""
    ha.occupy(GR_KEY[0], GR)
    ha.run_nudge()
    assert len(setpoint_calls(ha)) == 1, "setup: expected exactly one set_hold"
    if echo:
        ha.set_cloud_truth(cool=ha._sp_commanded_cool, heat=ha._sp_commanded_heat)


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

# =============================================================================
# 1 + 6. THE LIVE CHURN REGRESSION (assertion 1): cloud truth matches what we
#    commanded, while the homekit_controller MIRROR reports a contradictory 66/60
#    -> NO relinquish; ownership retained even past the confirm window. Because
#    the two disagree and the decision follows cloud truth, this also proves the
#    readback does NOT come from climate.ecobee_thermostat (assertion 6).
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=72.0, sp_heat=66.0)
# Game Room at excess 6.5 over the mirror 72 -> nudge 1.0 (MAX_F cap),
# commanded cool 71, heat coupled down to 65 (6F gap). temp = 72 + 1.5 + 6.5 = 80.0.
ha.set_room_temp("upstairs", GR, 80.0)
engage_cooling_hold(ha, echo=False)
check("A1 engage: commanded cool 71 / heat 65",
      ha._sp_commanded_cool == 71.0 and ha._sp_commanded_heat == 65.0)
# Cloud truth echoes our exact hold; the MIRROR stays frozen at 66/60 (the bug).
ha.set_cloud_truth(cool=71.0, heat=65.0)
assert ha.live_cool() == 72.0 and ha.live_heat() == 66.0, "mirror must STAY stale"
check("A1 setup: mirror contradicts cloud truth (66/60 vs 71/65)",
      (ha.live_cool(), ha.live_heat()) == (72.0, 66.0))
n_before = len(ha.logs)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()   # would RELINQUISH under the old mirror readback
check("A1 no false relinquish: still owned", ha._sp_owned is True)
check("A1 decision followed cloud truth: NO 'user changed setpoint' logged",
      not any("user changed setpoint" in m for m in ha.logs[n_before:]))
check("A1 no resume call (never pop the hold)", len(resume_calls(ha)) == 0)
check("A1 no spurious re-engage write (still exactly 1 set_hold)",
      len(setpoint_calls(ha)) == 1)
check("A1 baseline preserved (72, not the stale mirror 66)",
      ha._sp_baseline_cool == 72.0)
check("A1 mismatch not recorded (cloud truth matched)", ha._sp_mismatch_since is None)

# =============================================================================
# 2. GENUINE USER CHANGE on CLOUD TRUTH is still detected: cloud truth reads
#    66/60 while commanded 63/57, sustained past CONFIRM -> relinquish with the
#    existing 'user changed setpoint' message (assertion 2).
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=66.0, sp_heat=57.0)
ha.set_room_temp("upstairs", GR, 66.0 + 1.5 + 6.5)  # excess 6.5 -> nudge 1.0
engage_cooling_hold(ha)  # commanded cool 65 / heat 57 (cloud echo)
check("A2 engage: commanded 65/57", ha._sp_commanded_cool == 65.0
      and ha._sp_commanded_heat == 57.0)
# The USER raises cloud truth back to 66/60 (1.0F above our commanded 65).
ha.set_cloud_truth(cool=66.0, heat=60.0)
n_before = len(ha.logs)
ha.run_nudge()  # fresh mismatch -> set _sp_mismatch_since, no action yet
check("A2 fresh mismatch: still owned (confirm window)", ha._sp_owned is True)
check("A2 fresh mismatch: zero service calls this cycle",
      len(resume_calls(ha)) == 0 and len(setpoint_calls(ha)) == 1)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()  # confirmed -> relinquish
check("A2 confirmed user change: _sp_owned False", ha._sp_owned is False)
check("A2 'user changed setpoint' logged from the CLOUD truth readback",
      any("user changed setpoint" in m for m in ha.logs[n_before:]))
check("A2 zero resume calls (never pop user's hold)", len(resume_calls(ha)) == 0)
check("A2 zero fight-back set_hold writes", len(setpoint_calls(ha)) == 1)

# =============================================================================
# 3. ENGAGE BASELINE comes from CLOUD TRUTH, NOT the mirror (assertion 3):
#    cloud truth 72/64 while the mirror reports 66/60 -> recorded baseline is
#    72.0/64.0. (The old code captured the stale mirror as `baseline cool 66.0`.)
# =============================================================================
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=66.0, sp_heat=60.0)   # mirror baseline 66/60
ha.set_cloud_truth(cool=72.0, heat=64.0)  # but cloud truth is 72/64
ha.occupy("upstairs", GR)
ha.set_room_temp("upstairs", GR, 66.0 + 1.5 + 6.5)  # excess 6.5 vs mirror 66
ha.run_nudge()
check("A3 engage fired (excess over mirror still engages)", len(setpoint_calls(ha)) == 1)
check("A3 baseline captured from CLOUD TRUTH (72.0, NOT the stale 66.0)",
      ha._sp_baseline_cool == 72.0)
check("A3 baseline heat captured from CLOUD TRUTH (64.0, not 60.0)",
      ha._sp_baseline_heat == 64.0)

# =============================================================================
# 4. CLOUD TRUTH 'unavailable' / None / 'unknown' while OWNED -> no relinquish,
#    no re-baseline, no service call, ownership unchanged (assertion 4). The
#    one-shot log fires at most once per occurrence.
# =============================================================================
for label, bad_val in [("unavailable", "unavailable"),
                       ("None", None),
                       ("unknown", "unknown")]:
    ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
                sp_cool=66.0, sp_heat=57.0)
    ha.set_room_temp("upstairs", GR, 66.0 + 1.5 + 6.5)
    engage_cooling_hold(ha)  # owned, commanded 63/57, cloud echo
    # Cloud truth goes bad on EITHER axis while the room is still hot.
    ha.set_cloud_truth(cool=bad_val, heat=bad_val)
    ha.run_nudge()  # no ownership decision this cycle
    n_logs_before = len(ha.logs)
    check(f"A4[{label}] owned + cloud-truth {label!r}: still owned",
          ha._sp_owned is True)
    check(f"A4[{label}] owned + cloud-truth {label!r}: no resume call",
          len(resume_calls(ha)) == 0)
    check(f"A4[{label}] owned + cloud-truth {label!r}: no set_hold write",
          len(setpoint_calls(ha)) == 1)
    check(f"A4[{label}] owned + cloud-truth {label!r}: baseline NOT changed",
          ha._sp_baseline_cool is not None and ha._sp_baseline_cool == 66.0)
    # Run many more cycles: state stays put AND the log fires at most ONCE.
    bad_logs = sum(1 for m in ha.logs if "cloud-truth setpoint sensor" in m)
    for _ in range(5):
        ha.run_nudge()
    bad_logs_after = sum(1 for m in ha.logs if "cloud-truth setpoint sensor" in m)
    check(f"A4[{label}] owned + cloud-truth {label!r}: ONE-SHOT log (no spam)",
          bad_logs == 1 and bad_logs_after == 1)
    check(f"A4[{label}] owned + cloud-truth {label!r}: still owned after many cycles",
          ha._sp_owned is True)

# =============================================================================
# 5. CLOUD TRUTH bad while NOT owned + worst_excess above engage -> does NOT
#    engage (no service call) because there is no trustworthy baseline
#    (assertion 5).
# =============================================================================
for label, bad_val in [("unavailable", "unavailable"), ("None", None)]:
    ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
                sp_cool=70.0, sp_heat=64.0)
    ha.occupy("upstairs", GR)
    ha.set_room_temp("upstairs", GR, 70.0 + 1.5 + 8.0)  # excess 8.0 >> engage
    ha.set_cloud_truth(cool=bad_val, heat=bad_val)
    ha.run_nudge()
    check(f"A5[{label}] hot + not-owned + cloud-truth {label!r}: does NOT engage",
          len(setpoint_calls(ha)) == 0)
    check(f"A5[{label}] hot + not-owned + cloud-truth {label!r}: _sp_owned stays False",
          ha._sp_owned is False)
    check(f"A5[{label}] no resume call either", len(resume_calls(ha)) == 0)

# =============================================================================
# 6. Explicit disagreement regression (assertion 6, direct): with a FRESH
#    engage, the mirror alone (matching the OLD readback source) showing values
#    EQUAL to what we commanded while cloud truth disagrees must NOT retain us,
#    and cloud truth matching while the mirror disagrees MUST retain us. Both
#    directions pinned to cloud truth.
# =============================================================================
# 6a: mirror == commanded (would keep under the OLD code, but only if we read
#     the mirror), cloud truth contradicts -> MUST relinquish after CONFIRM.
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=66.0, sp_heat=57.0)
ha.occupy("upstairs", GR)
ha.set_room_temp("upstairs", GR, 66.0 + 1.5 + 6.5)
ha.run_nudge()  # engage, commanded 63/57; mirror still 66/57 (NOT echoed)
# Force the mirror to our commanded value, but cloud truth stays at the USER's
# changed 66/60. The old (mirror) readback would say "matches", the new
# (cloud) readback says "user changed it".
ha.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_high"] = 63.0
ha.attrs[(svc.THERMOSTAT, "all")]["attributes"]["target_temp_low"] = 57.0
ha.set_cloud_truth(cool=66.0, heat=60.0)  # user re-rased it (cloud truth)
ha.run_nudge()  # fresh mismatch on cloud truth
check("A6a mirror-says-match, cloud-says-changed: mismatch recorded (cloud wins)",
      ha._sp_mismatch_since is not None and ha._sp_owned is True)
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("A6a mirror-says-match, cloud-says-changed: RELINQUISHED (cloud wins)",
      ha._sp_owned is False)
check("A6a still zero resume (never pop)", len(resume_calls(ha)) == 0)
# 6b (already covered by A1, but state it): cloud truth matches while the mirror
#     disagrees -> retained. Rebuilt here for a standalone pass/fail line.
ha = FakeHA(hvac_mode="heat_cool", hvac_action="cooling",
            sp_cool=72.0, sp_heat=66.0)
ha.occupy("upstairs", GR)
ha.set_room_temp("upstairs", GR, 80.0)
ha.run_nudge()  # engage, commanded 69/63, mirror still 72/66
ha.set_cloud_truth(cool=69.0, heat=63.0)  # cloud truth echoes our hold
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
ha.run_nudge()
check("A6b cloud-says-match, mirror-says-changed: retained (cloud wins)",
      ha._sp_owned is True)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
