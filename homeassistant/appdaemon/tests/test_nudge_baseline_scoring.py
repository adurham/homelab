"""Offline validation of baseline-aware vent scoring during an active setpoint nudge.

THE BUG (fixed 2026-09-01): _apply_setpoint_nudge temporarily drives the
ecobee setpoint down (cooling) / up (heating) to force compressor escalation.
While the nudge is active, control_loop was passing the ARTIFICIALLY NUDGED
live setpoint into _auto_calculate / _apply_priority_rooms / _apply_fan_assist,
so every room's `need` was inflated by the nudge amount. Live production
result: EVERY room — including cool, unoccupied downstairs rooms — logged a
100% "hot override", every room qualified as a beneficiary, nobody qualified as
a donor, and the priority pass logged "struggling but no donor rooms" for all.
An occupant sat in the Living Room at only +0.5F over their 72F baseline while
the vent blasted 100% stage-2 air.

THE FIX: vent scoring now references the user's effective PRE-NUGE baseline
setpoint while the nudge is "owned AND live readback matches". One shared
helper (_active_nudge_baseline) returns (baseline_cool, baseline_heat) only in
that exact state; control_loop computes it ONCE per cycle and passes the
effective values into all three vent-scoring passes. When no nudge is trusted
live the helper returns None and the effective values equal the LIVE setpoints
byte-for-byte (zero behavior change otherwise).

ASYMMETRY (deliberate): ONLY the three vent-scoring call sites become
baseline-aware. _apply_setpoint_nudge's own worst_excess computation and
_update_delivery_penalties stay on LIVE setpoints — the nudge is a
compressor-pressure signal; feeding it the baseline would break its release
logic so it would never release. Test 9 is the regression guard proving the
nudge still computes worst_excess from the LIVE setpoint.

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
pkg_ad = types.ModuleType("appdaemon")
pkg_pl = types.ModuleType("appdaemon.plugins")
pkg_hs = types.ModuleType("appdaemon.plugins.hass")
sys.modules["appdaemon"] = pkg_ad
sys.modules["appdaemon.plugins"] = pkg_pl
sys.modules["appdaemon.plugins.hass"] = pkg_hs
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
    def __init__(self, mode="Auto"):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self.logs = []
        self.sp_calls = []   # (service, kwargs)
        self.fan_calls = []  # service names only
        self._clock = datetime(2026, 9, 1, 13, 0, 0)
        self._mode = mode
        # Handicap axes (default clean: no supply/delivery penalties).
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        # saturation state machine (2026-09-02)
        self._saturation_streak = {}
        self._saturated_rooms = set()
        self._saturation_recover = {}
        # Zone-presence + contention state.
        self._zone_last_occupied = {}
        self._zone_occupied = {}
        self._zone_vacancy_demoted = set()
        self._last_zone_positions = {}
        # Setpoint-nudge ownership state (seeded directly; initialize() would too).
        self._sp_owned = False
        self._sp_commanded_cool = None
        self._sp_commanded_heat = None
        self._sp_baseline_cool = None
        self._sp_baseline_heat = None
        self._sp_last_write_ts = None
        self._sp_mismatch_since = None
        self._sp_heating = None
        # Fan-assist / coil / backpressure state.
        self._fan_assist_active = False
        self._cooling_ended_at = None
        self._cooling_started_at = None
        self._last_hvac_action = None
        self._coil_emergency_latched = False
        self._coil_emergency_since = None
        self._coil_ratio_current = None
        self._coil_ratio_changed_at = None
        self._coil_sensor_fail_count = 0
        self._manual_holds = {}
        self._last_positions = {}
        # Thermostat state (live setpoints).
        self._hvac_mode = "heat_cool"
        self._hvac_action = "cooling"
        self._live_cool = 72.0
        self._live_heat = 60.0
        # Populate every room: neutral temp 71.0, occupancy "off".
        for zn, zone in svc.ZONES.items():
            for rn, s in zone["rooms"].items():
                self.states[s["temp"]] = 71.0
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
        if service == "ecobee_enhanced/set_fan_hold":
            self.fan_calls.append("on")
        elif service == "ecobee_enhanced/resume_top_event":
            self.fan_calls.append("auto")

    # ---- thermostat -----------------------------------------------------------
    def _set_thermostat(self):
        self.attrs[(svc.THERMOSTAT, "all")] = {
            "state": self._hvac_mode,
            "attributes": {
                "hvac_mode": self._hvac_mode,
                "hvac_action": self._hvac_action,
                "target_temp_high": self._live_cool,
                "target_temp_low": self._live_heat,
                "current_temperature": 72.0,
            },
        }
        # Cloud-truth setpoint sensors. Default to the (live) mirror values so
        # pre-existing behavior is unchanged; a test can diverge them with
        # set_cloud_truth(). Ownership readbacks follow THESE, not the mirror.
        self.states.setdefault(svc.SETPOINT_TRUTH_COOL, self._live_cool)
        self.states.setdefault(svc.SETPOINT_TRUTH_HEAT, self._live_heat)

    def set_cloud_truth(self, cool=None, heat=None, **dummy):
        """Set ONLY the cloud-truth setpoint sensors (leave the mirror alone)."""
        if cool is not None:
            self.states[svc.SETPOINT_TRUTH_COOL] = cool
        if heat is not None:
            self.states[svc.SETPOINT_TRUTH_HEAT] = heat

    def set_live_setpoints(self, cool=None, heat=None):
        """Simulate the live readback changing (our echo or a user change).

        A live ecobee write echo appears on BOTH the mirror AND the cloud-truth
        sensors, so keep them in sync.
        """
        if cool is not None:
            self._live_cool = float(cool)
        if heat is not None:
            self._live_heat = float(heat)
        self._set_thermostat()
        self.set_cloud_truth(cool=cool, heat=heat)

    def set_hvac_action(self, action):
        self._hvac_action = action
        self._set_thermostat()

    def set_room_temp(self, zone, room, temp):
        self.states[svc.ZONES[zone]["rooms"][room]["temp"]] = float(temp)

    def occupy(self, zone, room):
        s = svc.ZONES[zone]["rooms"][room]
        self.states[s["occupancy"]] = "on"
        self._zone_last_occupied[zone] = self._clock  # zone presence

    def seed_owned_nudge(self, cooling=True, baseline_cool=72.0,
                         baseline_heat=60.0, commanded_cool=66.0,
                         commanded_heat=60.0):
        """Seed _sp_owned = True with the given baseline/commanded values."""
        self._sp_owned = True
        self._sp_heating = not cooling
        self._sp_baseline_cool = baseline_cool
        self._sp_baseline_heat = baseline_heat
        self._sp_commanded_cool = commanded_cool
        self._sp_commanded_heat = commanded_heat

    def eff_setpoints(self):
        """What control_loop now computes: effective (cool, heat) for vent scoring."""
        bl = self._active_nudge_baseline(self._live_cool, self._live_heat)
        if bl:
            return bl
        return (self._live_cool, self._live_heat)

    def set_room(self, zone, room, temp, occupied):
        self.set_room_temp(zone, room, temp)
        if occupied:
            self.occupy(zone, room)


def find_key(ha, room):
    for zn, zone in svc.ZONES.items():
        if room in zone["rooms"]:
            return (zn, room)
    raise KeyError(room)


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


def setpoint_calls(ha):
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/set_hold_temperature"]


def resume_calls(ha):
    return [kw for svc_, kw in ha.sp_calls
            if svc_ == "ecobee_enhanced/resume_top_event"]


# =============================================================================
# Helpers to build the production-style nudge + room-temp scenario.
# Live (nudged): cool 66 / heat 60.  Baseline: cool 72 / heat 60.
# =============================================================================
def build_nudged_house(action="cooling"):
    """A cooling nudge owned + readback-matching at live cool 66 (baseline 72)."""
    ha = FakeHA()
    ha.seed_owned_nudge(cooling=True, baseline_cool=72.0, baseline_heat=60.0,
                        commanded_cool=66.0, commanded_heat=60.0)
    ha.set_live_setpoints(cool=66.0, heat=60.0)   # readback echoes our command
    ha.set_hvac_action(action)
    return ha


def set_production_temps(ha):
    """The 14 rooms from the live report (occupied = task's occupied list)."""
    temps = {
        ("upstairs", "Game Room"): (75.0, True),
        ("upstairs", "Guest Bedroom 2"): (72.9, False),
        ("upstairs", "Guest Bedroom 1"): (72.3, False),
        ("upstairs", "Cat Room"): (70.8, False),
        ("upstairs", "Guest Bathroom"): (69.5, False),
        ("downstairs", "Kitchen"): (72.6, True),   # no occ sensor -> assumed occ
        ("downstairs", "Living Room"): (72.5, True),
        ("downstairs", "Laundry Room"): (72.2, True),
        ("downstairs", "Main Bathroom"): (71.5, True),
        ("downstairs", "Main Bedroom"): (70.7, True),
        ("downstairs", "Dining Room"): (70.4, True),
        ("basement", "Basement"): (69.9, False),
    }
    for (z, rn), (t, occ) in temps.items():
        ha.set_room(z, rn, t, occupied=occ)
    # Hallway has no occupancy sensor (pass-through) — treat occupied-neutral.
    ha.set_room_temp("downstairs", "Hallway", 71.0)


# =============================================================================
# 1. NO-NUDGE IDENTITY: helper returns None; _auto_calculate output identical
#    to pre-change expectations (effective == live when no nudge is trusted).
# =============================================================================
ha = FakeHA()
ha.set_live_setpoints(cool=72.0, heat=60.0)
ha.set_hvac_action("cooling")
check("T1 no-nudge: _active_nudge_baseline returns None",
      ha._active_nudge_baseline(72.0, 60.0) is None)
check("T1 no-nudge: eff_setpoints == live (byte-identical)",
      ha.eff_setpoints() == (72.0, 60.0))
out = ha._auto_calculate(ha._hvac_mode, ha._hvac_action, 72.0, 60.0)
lr = find_key(ha, "Living Room")
check("T1 no-nudge: Living Room 71.0 (empty) -> 0% (satisfied, exactly as today)",
      out.get(lr) == 0)
check("T1 no-nudge: _sp_owned stays False", ha._sp_owned is False)

# =============================================================================
# 2. ACTIVE-NUDGE BASELINE SUBSTITUTION in _auto_calculate: with live cool 66 /
#    baseline 72, Living Room 72.5 must NOT be hot-overridden to 100%. Under the
#    (buggy) LIVE reference it would be need=+7.5 -> hot override 100%; under
#    the baseline it is raw 0.5F over setpoint -> under the 2026-09-02
#    downstairs-occupied-cooling-ladder's 1.0F open threshold -> 0% (closed).
# =============================================================================
ha = build_nudged_house(action="cooling")
set_production_temps(ha)
check("T2 active-nudge: _active_nudge_baseline returns (72.0, 60.0)",
      ha.eff_setpoints() == (72.0, 60.0))
eff_cool, eff_heat = ha.eff_setpoints()
base_out = ha._auto_calculate(ha._hvac_mode, ha._hvac_action, eff_cool, eff_heat)
lr = find_key(ha, "Living Room")
# Sanity: the LIVE reference (the bug) WOULD give 100%.
live_out = ha._auto_calculate(ha._hvac_mode, "cooling", 66.0, 60.0)
check("T2 bug-confirm: with LIVE 66 the Living Room hot-overrides to 100%",
      live_out.get(lr) == 100)
check("T2 fix: with BASELINE 72 the Living Room is NOT hot-overridden (0%, "
      "raw 0.5F under the 1.0F downstairs-occupied ladder open threshold)",
      base_out.get(lr) == 0)
# Game Room must stay 100% (it IS genuinely hot: +3.0 over baseline).
gr = find_key(ha, "Game Room")
check("T2 fix: Game Room stays 100% (genuinely hot over baseline)", base_out.get(gr) == 100)

# =============================================================================
# 3. PRIORITY-PASS DONOR QUALIFICATION: Living Room 72.5 no longer a beneficiary
#    while Game Room 75.0 IS; downstairs rooms become donors throttled to 0%
#    (Game Room escalates via its 1.5F override -> donor_pos 0).
# =============================================================================
ha = build_nudged_house(action="cooling")
set_production_temps(ha)
eff_cool, eff_heat = ha.eff_setpoints()
auto = ha._auto_calculate(ha._hvac_mode, ha._hvac_action, eff_cool, eff_heat)
out = ha._apply_priority_rooms(auto, "cooling", eff_cool, eff_heat, "Auto")
gr = find_key(ha, "Game Room")
lr = find_key(ha, "Living Room")
check("T3 Game Room pinned 100% (beneficiary)", out.get(gr) == 100)
# Living Room is NOT a beneficiary (off 0.5 < margin 1.5 against baseline 72),
# so it is a donor candidate (cooler than 75-1.5). With escalation it hits 0%.
check("T3 Living Room not a beneficiary (throttled as donor, <100)",
      out.get(lr) < 100)
# At least the coolest downstream/downstairs rooms get fully throttled to 0%
# because Game Room escalated (donor_pos=0). Expect several at 0.
closed_lv = [k for k, v in out.items() if v == 0]
check("T3 Game Room escalated: at least 2 donors throttled to 0%", len(closed_lv) >= 2)
print("    closed donors:", ", ".join(f"{k[1]}={out[k]}" for k in closed_lv[:8]))

# =============================================================================
# 4. FAN-ASSIST WIRING uses the same effective setpoints. Cooling nudge owned+
#    match, compressor drops to idle, Game Room mildly over the 72 baseline
#    (off 1.5 < FAN_ASSIST_OVER 2.0). With the BASELINE the blower must NOT
#    engage; with the LIVE 66 it WOULD (off 7.5) and waste the blower.
# =============================================================================
ha = build_nudged_house(action="idle")
set_production_temps(ha)
ha.set_hvac_action("idle")
# Isolate: only Game Room hot-mildly over baseline; make everything else cool so
# no donor is banked hot. Game Room 73.5: baseline off 1.5, LIVE off 7.5.
ha.set_room("upstairs", "Game Room", 73.5, True)
eff_cool, eff_heat = ha.eff_setpoints()
assert eff_cool == 72.0
pos = {(zn, rn): 100 for zn, zone in svc.ZONES.items()
       for rn in zone["rooms"]}
out = ha._apply_fan_assist(pos, "Auto", "idle", eff_cool, eff_heat)
check("T4 fan-assist with BASELINE: blower NOT engaged (room only +1.5 over 72)",
      ha.fan_calls == [])
# Contrast: same room but pass the LIVE (buggy) setpoints -> would engage blower.
ha2 = build_nudged_house(action="idle")
set_production_temps(ha2)
ha2.set_hvac_action("idle")
ha2.set_room("upstairs", "Game Room", 73.5, True)
pos2 = {(zn, rn): 100 for zn, zone in svc.ZONES.items()
        for rn in zone["rooms"]}
out2 = ha2._apply_fan_assist(pos2, "Auto", "idle", 66.0, 60.0)
check("T4 bug-confirm: with LIVE 66 fan-assist WOULD engage blower (off 7.5)",
      "on" in ha2.fan_calls)

# =============================================================================
# 5. MISMATCH / CONFIRM-WINDOW FALLBACK: owned + FRESH readback mismatch ->
#    helper returns None -> callers use LIVE. The in-flight echo must be treated
#    as unconfirmed, exactly like _apply_setpoint_nudge's confirm window.
# =============================================================================
ha = build_nudged_house(action="cooling")
set_production_temps(ha)
# Owned, but live cool no longer matches commanded (e.g. first echo still 67.0).
ha.set_live_setpoints(cool=67.0, heat=60.0)
check("T5 mismatch: _active_nudge_baseline returns None (unconfirmed)",
      ha._active_nudge_baseline(67.0, 60.0) is None)
check("T5 mismatch: eff_setpoints fall back to LIVE 67.0 (not baseline)",
      ha.eff_setpoints() == (67.0, 60.0))
# Ownership is still held inside the confirm window (relinquish machinery not fired).
check("T5 mismatch: _sp_owned still True (inside confirm window)",
      ha._sp_owned is True)

# =============================================================================
# 6. USER MANUAL CHANGE -> EXISTING RELINQUISH MACHINERY fires -> helper returns
#    None on the next cycle. No new relinquish logic added.
# =============================================================================
ha = build_nudged_house(action="cooling")
set_production_temps(ha)
# The USER changes the cool setpoint to 70 (2.0F above our commanded 66).
ha.set_live_setpoints(cool=70.0, heat=60.0)
mode, action, tc, th = ha._get_thermostat_state()
ha._apply_setpoint_nudge(mode, action, tc, th, "Auto")   # fresh mismatch -> set _sp_mismatch_since
ha.advance(svc.SETPOINT_NUDGE_CONFIRM_SEC + 1)
mode, action, tc, th = ha._get_thermostat_state()
ha._apply_setpoint_nudge(mode, action, tc, th, "Auto")   # confirmed -> relinquish
check("T6 user-change: relinquished (not owned)", ha._sp_owned is False)
check("T6 user-change: baseline cleared", ha._sp_baseline_cool is None)
check("T6 user-change: helper returns None after relinquish",
      ha._active_nudge_baseline(70.0, 60.0) is None)
check("T6 user-change: zero resume calls (never pop user's hold)",
      len(resume_calls(ha)) == 0)

# =============================================================================
# 7. HEATING SYMMETRY: heating-direction nudge uses baseline_heat. Baseline
#    heat 68, nudge raises to live 71, owned+match on the heat axis. A warm room
#    at 70 is COMFORTABLE vs baseline heat 68 (need -1.0 -> 0%) but would read
#    need +3.0 (100%) against the LIVE 71.
# =============================================================================
ha = FakeHA()
ha.seed_owned_nudge(cooling=False, baseline_cool=74.0, baseline_heat=68.0,
                    commanded_cool=74.0, commanded_heat=71.0)
ha.set_live_setpoints(cool=74.0, heat=71.0)   # readback echoes the raised heat
ha.set_hvac_action("heating")
check("T7 heating-nudge: _active_nudge_baseline returns (74.0, 68.0)",
      ha._active_nudge_baseline(74.0, 71.0) == (74.0, 68.0))
# A warm room at 70.0 (already above the heat baseline 68): baseline => need < 0.
ha.set_room("upstairs", "Game Room", 70.0, True)
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn == "Game Room":
            continue
        ha.set_room_temp(zn, rn, 72.0)
# Keep the zone occupied (Game Room is) so no vacancy override kicks in.
eff_cool, eff_heat = ha.eff_setpoints()
assert eff_heat == 68.0
out = ha._auto_calculate("heat_cool", "heating", eff_cool, eff_heat)
gr = find_key(ha, "Game Room")
check("T7 heat baseline: Game Room 70.0 (above heat baseline 68) -> 0%, not 100%",
      out.get(gr) == 0)
# Live reference (the bug) would give need = 71-70 = 1.0 + occ_bonus 1.0 = 2.0.
out_live = ha._auto_calculate("heat_cool", "heating", 74.0, 71.0)
check("T7 bug-confirm: with LIVE heat 71 the same room reads need +2.0 -> 100%",
      out_live.get(gr) == 100)

# =============================================================================
# 8. NO-NUDGE GUARANTEE: re-run key scenarios with NO nudge state and confirm
#    the outputs are byte-identical whether we pass live or eff (=live here).
# =============================================================================
ha = FakeHA()
ha.set_live_setpoints(cool=72.0, heat=60.0)
ha.set_hvac_action("cooling")
set_production_temps(ha)  # same temps as T2, but no nudge state
assert ha._active_nudge_baseline(72.0, 60.0) is None
out_live = ha._auto_calculate("heat_cool", "cooling", 72.0, 60.0)
out_eff = ha._auto_calculate("heat_cool", "cooling", *ha.eff_setpoints())
check("T8 no-nudge: _auto_calculate identical whether eff or live passed",
      out_live == out_eff)
lr = find_key(ha, "Living Room")
gr = find_key(ha, "Game Room")
check("T8 no-nudge: Living Room 72.5 occupied raw+0.5 -> 0% (under the "
      "2026-09-02 downstairs-occupied ladder's 1.0F open threshold)",
      out_eff.get(lr) == 0)
check("T8 no-nudge: Game Room still 100% (genuinely hot over 72)",
      out_eff.get(gr) == 100)

# =============================================================================
# 9. ASYMMETRY REGRESSION GUARD: _apply_setpoint_nudge STILL computes
#    worst_excess from the LIVE setpoint, not the baseline. Game Room at 70.0,
#    owned cooling nudge with echo (live cool 66, baseline 72). vs LIVE 66:
#    off 4.0, excess 2.5 > RELEASE 0.5 -> nudge retained. If it wrongly used the
#    baseline 72, off would be -2.0 -> excess 0 -> it would RELEASE. So "still
#    owned after this cycle" proves the nudge's own math is on the LIVE setpoint.
# =============================================================================
ha = build_nudged_house(action="cooling")
ha.set_room("upstairs", "Game Room", 70.0, True)   # off 4.0 vs live 66
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn == "Game Room":
            continue
        ha.set_room_temp(zn, rn, 71.0)              # neutral, below live
        if s.get("occupancy"):
            ha.states[s["occupancy"]] = "off"
mode, action, tc, th = ha._get_thermostat_state()
ha._apply_setpoint_nudge(mode, action, tc, th, "Auto")
check("T9 asymmetry: nudge retained (worst_excess measured vs LIVE 66, not baseline 72)",
      ha._sp_owned is True)
check("T9 asymmetry: zero resume calls", len(resume_calls(ha)) == 0)
check("T9 asymmetry: zero new set_hold writes", len(setpoint_calls(ha)) == 0)
# And the SAME live readback still yields a trustworthy baseline for vent scoring.
check("T9 asymmetry: vent scoring still uses baseline 72 via the helper",
      ha._active_nudge_baseline(66.0, 60.0) == (72.0, 60.0))

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
