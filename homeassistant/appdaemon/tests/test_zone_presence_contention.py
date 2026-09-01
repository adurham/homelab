"""Offline validation of the zone-presence contention axis (measured axis).

Encodes the acceptance assertions for the 2026-08-31 fix to the production
bug where empty downstairs rooms locked themselves into protected-beneficiary
status (OCCUPANCY_OVERRIDE_OVER = absolute +3.0F) and could never be donors,
so the occupied Game Room (77F) was starved while the ecobee read a
whole-house average near setpoint.

Mechanism under test (levers, both active in the priority pass AND the
fan-assist pass):
  A) OCCUPANCY_OVERRIDE_OVER becomes RELATIVE for vacant zones: an unoccupied
     room in a vacant zone whose occupants elsewhere are suffering
     (contention) must be considerably hotter before it can re-lock into
     protected-beneficiary status. Raise = OVER + ZONE_VACANCY_OVERRIDE_BONUS_F*c,
     capped at ZONE_VACANCY_OVERRIDE_CEILING_F (bake protection), with
     hysteresis (ZONE_VACANCY_OVERRIDE_HYST_F) to prevent donor/beneficiary
     flapping.
  B) Donor eligibility relaxes for rooms in vacant zones, proportional to
     contention: the "must be cooler by" requirement is waived fractionally
     (ZONE_VACANCY_DONOR_RELAX) but never below ZONE_VACANCY_DONOR_MIN_COOLER_F
     (thermodynamic guard).

Also covers presence-hold (debounce) and heating/cooling symmetry.

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

# ---- fake HA backend ---------------------------------------------------------
class FakeHA(svc.SmartVentController):
    def __init__(self):
        self.states = {}
        self.attrs = {}
        self.published = {}
        self._clock = datetime(2026, 8, 31, 15, 0, 0)
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self._delivery_last = {}
        self._zone_last_occupied = {}
        self._zone_occupied = {}
        self._zone_vacancy_demoted = set()
        self._last_zone_positions = {}
        self._fan_assist_active = False
        self._cooling_ended_at = None
        self.fan_calls = []
        self.logs = []
    def datetime(self, aware=False):
        return self._clock
    def advance(self, minutes):
        self._clock += timedelta(minutes=minutes)
    def get_state(self, entity, attribute=None):
        if attribute:
            return self.attrs.get((entity, attribute))
        return self.states.get(entity)
    def set_state(self, entity, state=None, attributes=None):
        self.published[entity] = (state, attributes or {})
    def log(self, msg, *a, **k):
        self.logs.append(msg)
    def call_service(self, service, **kwargs):
        if service == "ecobee_enhanced/set_fan_hold":
            self.fan_calls.append("on")
        elif service == "ecobee_enhanced/resume_top_event":
            self.fan_calls.append("auto")


def fresh():
    ha = FakeHA()
    for _zn, zone in svc.ZONES.items():
        for _rn, s in zone["rooms"].items():
            ha.states[s["temp"]] = 72.0
            if s.get("occupancy"):
                ha.states[s["occupancy"]] = "off"
            for v in s.get("vents", []):
                ha.attrs[(v, "current_tilt_position")] = 100
    return ha


def find_key(ha, room):
    for zn, zone in svc.ZONES.items():
        if room in zone["rooms"]:
            return (zn, room)
    raise KeyError(room)


def set_thermostat(ha, sp_cool=70.0, sp_heat=60.0, action="cooling"):
    state = "cool" if action == "cooling" else ("heat" if action == "heating" else "idle")
    ha.attrs[(svc.THERMOSTAT, "all")] = {
        "state": state,
        "attributes": {
            "hvac_action": action,
            "target_temp_high": sp_cool,
            "target_temp_low": sp_heat,
        },
    }


def all100():
    return {(zn, rn): 100
            for zn, zone in svc.ZONES.items()
            for rn in zone["rooms"]}


def presence(ha):
    ha._update_zone_presence()


PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)


SP = 70.0  # cool setpoint for the scenario tests
HEAT_SP = 70.0  # heat setpoint for the symmetry test

# =============================================================================
# 1. NO-REGRESSION / SAFETY: whole house empty -> contention exactly 0.0 and a
#    solar-baked empty room still gets 100% exactly as it does today.
# =============================================================================
ha = fresh()
set_thermostat(ha, action="cooling")
occ_entity = svc.ZONES["downstairs"]["rooms"]["Dining Room"]["occupancy"]
ha.states[occ_entity] = "off"
temp_e = svc.ZONES["downstairs"]["rooms"]["Dining Room"]["temp"]
ha.states[temp_e] = SP + 3.5  # past OCCUPANCY_OVERRIDE_OVER, but no contention
presence(ha)
check("T1 whole-house-empty: _zone_contention(downstairs) == 0.0 exactly",
      ha._zone_contention("downstairs", heating=False) == 0.0)
pos = all100()
auto = ha._auto_calculate("cool", "cooling", SP, 60.0)
out = ha._apply_priority_rooms(auto, "cooling", SP, None, "Auto")
dkey = find_key(ha, "Dining Room")
check("T1 a baking empty room in an empty house still ends at 100%",
      out[dkey] == 100)
print("    Dining Room position:", out[dkey], "(off-by", round(SP + 3.5 - SP, 1), "F)")

# =============================================================================
# 2. TONIGHT'S REAL SCENARIO: Game Room 77F occupied; empty downstairs rooms
#    near setpoint that used to lock to 100% (and could never be donors).
# =============================================================================
ha = fresh()
set_thermostat(ha, action="cooling")
gr = svc.ZONES["upstairs"]["rooms"]["Game Room"]
ha.states[gr["occupancy"]] = "on"
ha.states[gr["temp"]] = 77.0
# The four empty downstairs rooms from the bug report (temps near setpoint).
for rn, t in [("Dining Room", 73.0), ("Laundry Room", 73.0),
              ("Hallway", 71.0), ("Kitchen", 71.0)]:
    s = svc.ZONES["downstairs"]["rooms"][rn]
    ha.states[s["temp"]] = t
    if s.get("occupancy"):
        ha.states[s["occupancy"]] = "off"
# Keep every other room comfortably below setpoint / demotable so the empty
# downstairs rooms are the donors that actually get throttled (cap = 8).
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn in ("Game Room", "Dining Room", "Laundry Room", "Hallway", "Kitchen"):
            continue
        ha.states[s["temp"]] = 71.0
        if s.get("occupancy"):
            ha.states[s["occupancy"]] = "off"
presence(ha)
c = ha._zone_contention("downstairs", heating=False)
check("T2 real scenario: contention(downstairs) > 0 (someone upstairs suffering)",
      c > 0.0)
pos = all100()
auto = ha._auto_calculate("cool", "cooling", SP, 60.0)
out = ha._apply_priority_rooms(auto, "cooling", SP, None, "Auto")
gkey = find_key(ha, "Game Room")
check("T2 occupied Game Room ends at 100%", out[gkey] == 100)
dining = find_key(ha, "Dining Room")
laundry = find_key(ha, "Laundry Room")
check("T2 Dining Room (empty, vacant zone) no longer pinned 100% -> demoted donor",
      out[dining] < 100)
check("T2 Laundry Room (empty, vacant zone) no longer pinned 100% -> demoted donor",
      out[laundry] < 100)
check("T2 at least two of the empty downstairs rooms end at 0%",
      sum(out[k] == 0 for k in (dining, laundry,
                                find_key(ha, "Hallway"), find_key(ha, "Kitchen"))) >= 2)
print("    Game Room:", out[gkey], "| Dining:", out[dining],
      "| Laundry:", out[laundry], "(contention", round(c, 2), ")")

# =============================================================================
# 3. BAKE-PROTECTION CEILING: a genuinely baking vacant room past the ceiling
#    (ZONE_VACANCY_OVERRIDE_CEILING_F) still gets 100%, even at full contention.
# =============================================================================
ha = fresh()
set_thermostat(ha, action="cooling")
ha.states[gr["occupancy"]] = "on"
ha.states[gr["temp"]] = 77.0
ds = svc.ZONES["downstairs"]["rooms"]["Dining Room"]
ha.states[ds["occupancy"]] = "off"
ha.states[ds["temp"]] = SP + 7.0  # above the ceiling
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn in ("Game Room", "Dining Room"):
            continue
        ha.states[s["temp"]] = 71.0
        if s.get("occupancy"):
            ha.states[s["occupancy"]] = "off"
presence(ha)
pos = all100()
auto = ha._auto_calculate("cool", "cooling", SP, 60.0)
out = ha._apply_priority_rooms(auto, "cooling", SP, None, "Auto")
check("T3 baking room past the ceiling is helped (100%) even at contention",
      out[find_key(ha, "Dining Room")] == 100)
print("    Dining Room position:", out[find_key(ha, "Dining Room")],
      "(off-by 7.0F, ceiling", svc.ZONE_VACANCY_OVERRIDE_CEILING_F, "F)")

# =============================================================================
# 4. HEATING SYMMETRY: occupied downstairs Living Room cold; upstream GB1 empty
#    in a vacant zone does NOT lock as beneficiary and IS available as a donor.
# =============================================================================
ha = fresh()
set_thermostat(ha, action="heating", sp_cool=None, sp_heat=HEAT_SP)
lr = svc.ZONES["downstairs"]["rooms"]["Living Room"]
ha.states[lr["occupancy"]] = "on"
ha.states[lr["temp"]] = 65.0  # 5F below heat setpoint
gb1 = svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]
ha.states[gb1["occupancy"]] = "off"
ha.states[gb1["temp"]] = 66.5  # 3.5F below heat setpoint
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn in ("Living Room", "Guest Bedroom 1"):
            continue
        ha.states[s["temp"]] = 64.5  # demotable in vacant zones
        if s.get("occupancy"):
            ha.states[s["occupancy"]] = "off"
presence(ha)
pos = all100()
out = ha._apply_priority_rooms(dict(pos), "heating", None, HEAT_SP, "Auto")
gb1k = find_key(ha, "Guest Bedroom 1")
check("T4 heat: GB1 (empty, vacant zone) does NOT lock as beneficiary",
      out[gb1k] < 100)
check("T4 heat: GB1 is selectable as a donor (position < 100) feeding Living Room",
      out[gb1k] < 100)
check("T4 heat: occupied Living Room beneficiary ends at 100%",
      out[find_key(ha, "Living Room")] == 100)
print("    GB1 position:", out[gb1k], "| Living Room:", out[find_key(ha, "Living Room")])

# =============================================================================
# 5. PRESENCE HOLD (debounce): a zone whose last occupancy was < HOLD minutes
#    ago still counts OCCUPIED (rooms not demoted); past HOLD it is vacant.
# =============================================================================
ha = fresh()
set_thermostat(ha, action="cooling")
game_s = svc.ZONES["upstairs"]["rooms"]["Game Room"]
ha.states[game_s["occupancy"]] = "on"
ha.states[game_s["temp"]] = SP + 4.0
lr = svc.ZONES["downstairs"]["rooms"]["Living Room"]
ha.states[lr["occupancy"]] = "on"
ha.states[lr["temp"]] = SP + 4.0
presence(ha)
# Game Room person leaves; zone should still count OCCUPIED within the window.
ha.states[game_s["occupancy"]] = "off"
ha.advance(5)  # 5 min < ZONE_PRESENCE_HOLD_MIN
presence(ha)
check("T5 zone stays OCCUPIED within the hold window (5m < HOLD)",
      not ha._zone_is_vacant("upstairs"))
# Rooms in a still-OCCUPIED zone are NOT demoted.
pos = all100()
out5a = ha._apply_priority_rooms(dict(pos), "cooling", SP, None, "Auto")
check("T5 Game Room NOT demoted while its zone is still OCCUPIED",
      find_key(ha, "Game Room") not in ha._zone_vacancy_demoted)
# Now advance past the hold window -> zone vacant -> room demoted.
ha.advance(26)  # total 31 min > HOLD
presence(ha)
check("T5 past the hold window the zone is vacant",
      ha._zone_is_vacant("upstairs"))
out5b = ha._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
check("T5 Game Room IS demoted once the zone goes vacant",
      find_key(ha, "Game Room") in ha._zone_vacancy_demoted)
print("    hold minutes:", svc.ZONE_PRESENCE_HOLD_MIN,
      "| demoted within window:", find_key(ha, "Game Room") in ha._zone_vacancy_demoted)

# =============================================================================
# 6. HYSTERESIS: a demoted room does not re-promote at the exact raised
#    boundary; it must exceed raised + ZONE_VACANCY_OVERRIDE_HYST_F. No flap
#    across consecutive cycles sitting on the boundary.
# =============================================================================
ha = fresh()
set_thermostat(ha, action="cooling")
ha.states[gr["occupancy"]] = "on"
ha.states[gr["temp"]] = 77.0   # contention 1.0 -> raised = OVER + BONUS = 6.0
d_s = svc.ZONES["downstairs"]["rooms"]["Dining Room"]
ha.states[d_s["occupancy"]] = "off"
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn in ("Game Room", "Dining Room"):
            continue
        ha.states[s["temp"]] = 71.0
        if s.get("occupancy"):
            ha.states[s["occupancy"]] = "off"
presence(ha)
# Content = 1.0 here, so raised = OVER + BONUS = 6.0 (below the 6.5 ceiling).
raised = svc.OCCUPANCY_OVERRIDE_OVER + svc.ZONE_VACANCY_OVERRIDE_BONUS_F
assert raised == 6.0, raised

# Keep the OTHER rooms HOTTER than the Game Room (77) so they are NOT donor-
# eligible (a donor must be cooler than its beneficiary) — Dining Room is then
# the only donor, so the 8-donor cap can't push it out of the throttled set.
for znx, zx in svc.ZONES.items():
    for rnx, sx in zx["rooms"].items():
        if rnx in ("Game Room", "Dining Room"):
            continue
        ha.states[sx["temp"]] = SP + 8.0  # hotter than Game Room: never a donor

# Cycle A: off 5.0 (< raised) -> demoted (becomes a donor).
ha.states[d_s["temp"]] = SP + 5.0
outA = ha._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
dk = find_key(ha, "Dining Room")
check("T6 cycle A: off<raised is demoted (donor, not 100)",
      outA[dk] < 100 and dk in ha._zone_vacancy_demoted)
# Cycle B: exactly on the raised boundary -> MUST stay demoted (no flap).
ha.states[d_s["temp"]] = SP + raised
outB = ha._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
check("T6 cycle B: at raised == boundary it stays demoted (no flap)",
      outB[dk] < 100 and dk in ha._zone_vacancy_demoted)
# Cycle C: past raised + HYST -> re-promoted to protected beneficiary (100%).
hyst_at = raised + svc.ZONE_VACANCY_OVERRIDE_HYST_F
ha.states[d_s["temp"]] = SP + hyst_at + 0.1
outC = ha._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
check("T6 cycle C: past raised+HYST -> re-promoted to 100%",
      outC[dk] == 100 and dk not in ha._zone_vacancy_demoted)
print("    raised:", raised, "| HYST:", svc.ZONE_VACANCY_OVERRIDE_HYST_F,
      "| A/B/C positions:", outA[dk], outB[dk], outC[dk])

# =============================================================================
# 7. FAN-ASSIST PARITY: the same vacant-zone demotion + donor relaxation is
#    live in _apply_fan_assist (idle/fan pass), matching the priority pass.
# =============================================================================
def build_idle_scene():
    h = fresh()
    set_thermostat(h, action="idle")
    h.states[gr["occupancy"]] = "on"
    h.states[gr["temp"]] = 77.0
    h.states[d_s["occupancy"]] = "off"
    h.states[d_s["temp"]] = SP + 3.0      # off 3.0 -> demoted in vacant zone
    for zn, zone in svc.ZONES.items():
        for rn, s in zone["rooms"].items():
            if rn in ("Game Room", "Dining Room"):
                continue
            # Hotter than Game Room -> these rooms are NOT donor-eligible (a
            # donor must be more comfortable than its beneficiary), so Dining
            # Room is the only donor and the 8-donor cap can't omit it.
            h.states[s["temp"]] = SP + 8.0
            if s.get("occupancy"):
                h.states[s["occupancy"]] = "off"
    presence(h)
    return h

ha = build_idle_scene()
outF = ha._apply_fan_assist(dict(all100()), "Auto", "idle", SP, 60.0)
dining = find_key(ha, "Dining Room")
check("T7 fan-assist: Dining (vacant zone) demoted, not a beneficiary (no 100%)",
      outF[dining] < 100)
check("T7 fan-assist: Dining selected as donor feeding Game Room",
      outF[dining] < 100)
check("T7 fan-assist: Game Room open 100%",
      outF[find_key(ha, "Game Room")] == 100)
check("T7 fan-assist engaged the blower",
      ha._fan_assist_active is True)
# Priority pass on identical inputs chooses the same donor (parity).
haP = build_idle_scene()
outP = haP._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
check("T7 priority pass selects the same donor for the same temps",
      outP[find_key(haP, "Dining Room")] < 100)
print("    Dining pos (fan-assist):", outF[dining],
      "| Dining pos (priority):", outP[find_key(haP, "Dining Room")])

# =============================================================================
# Observability: the new axis is published (string coercion pattern, not a
# bare float state).
# =============================================================================
haO = build_idle_scene()
haO._update_zone_presence()
check("OBS zone-presence sensor published",
      svc.ZONE_PRESENCE_ENTITY in haO.published)
if svc.ZONE_PRESENCE_ENTITY in haO.published:
    st, _at = haO.published[svc.ZONE_PRESENCE_ENTITY]
    check("OBS published state is a string (coerced, not a bare float)",
          isinstance(st, str))

# =============================================================================
# 8. REGRESSION: TWO OCCUPIED ZONES — donor relaxation must NOT apply to an
#    OCCUPIED (non-vacant) zone even when contention for it is non-zero.
#    Fixed 2026-08-31: _donor_cooler_by now guards on _zone_is_vacant(donor_zone)
#    at the top, so the contention-based relaxation is reserved for VACANT zones.
#    Previously the entire suite only had ONE occupied zone, where contention
#    for that zone is always 0.0 (its own zone is excluded) and the missing
#    guard was masked.
# =============================================================================
# Cooling, cool setpoint 70:
#   upstairs Game Room    77.0F  "on"   (struggling occupant, the beneficiary)
#   upstairs Guest Bedr.1 72.0F  "off"
#   downstairs Living Rm  74.0F  "on"   (a SECOND, genuinely occupied zone)
#   downstairs Dining Rm  71.0F  "off"
#   basement              72.0F  "off"
# Both "upstairs" and "downstairs" are non-vacant. _zone_contention("downstairs")
# sees Game Room's excess -> non-zero, which (before the fix) wrongly relaxed the
# donor requirement for the OCCUPIED downstairs zone.
def build_two_occupied():
    h = fresh()
    set_thermostat(h, action="cooling")
    gr_s = svc.ZONES["upstairs"]["rooms"]["Game Room"]
    h.states[gr_s["occupancy"]] = "on"
    h.states[gr_s["temp"]] = 77.0
    gb1_s = svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]
    h.states[gb1_s["occupancy"]] = "off"
    h.states[gb1_s["temp"]] = 72.0
    lr_s = svc.ZONES["downstairs"]["rooms"]["Living Room"]
    h.states[lr_s["occupancy"]] = "on"
    h.states[lr_s["temp"]] = 74.0
    dr_s = svc.ZONES["downstairs"]["rooms"]["Dining Room"]
    h.states[dr_s["occupancy"]] = "off"
    h.states[dr_s["temp"]] = 71.0
    for zn, zone in svc.ZONES.items():
        for rn, s in zone["rooms"].items():
            if rn in ("Game Room", "Living Room"):
                continue
            if s.get("occupancy"):
                h.states[s["occupancy"]] = "off"
    presence(h)
    return h


ha8 = build_two_occupied()
# B: contention for the OCCUPIED downstairs zone is genuinely non-zero (the
# Game Room upstairs is suffering) — this is the path the old suite never
# exercised, so the test would trivially pass if contention happened to be 0.
cont8 = ha8._zone_contention("downstairs", heating=False)
check("T8 B: contention(downstairs) > 0 while downstairs is OCCUPIED",
      cont8 > 0.0)
# A: the donor requirement for the OCCUPIED downstairs zone must stay EXACTLY
# at PRIORITY_DONOR_COOLER_BY — relaxation is reserved for VACANT zones.
got8a = ha8._donor_cooler_by("downstairs", svc.PRIORITY_DONOR_COOLER_BY, False)
check("T8 A: _donor_cooler_by(downstairs OCCUPIED) == PRIORITY_DONOR_COOLER_BY exactly",
      got8a == svc.PRIORITY_DONOR_COOLER_BY)
print(f"    contention(downstairs)={cont8:.3f} | donor_cooler_by={got8a:.3f} "
      f"({'relaxed(!)' if got8a < svc.PRIORITY_DONOR_COOLER_BY else 'unchanged'})")
# D: end-to-end through _apply_priority_rooms, the OCCUPIED Living Room keeps
# its normal protection (100% as beneficiary), never throttled to 0% as a donor.
ha8d = build_two_occupied()
out8 = ha8d._apply_priority_rooms(dict(all100()), "cooling", SP, None, "Auto")
lr8_key = find_key(ha8d, "Living Room")
check("T8 D: e2e occupied Living Room NOT throttled to 0% (keeps its 100%)",
      out8[lr8_key] == 100)
print(f"    Living Room position: {out8[lr8_key]}")

# C: still-vacant zones KEEP the relaxation — with upstairs occupied+struggling
# and downstairs fully vacant (never occupied, so past the hold), the donor
# requirement IS relaxed below base and floored at the thermodynamic guard.
# (Proves the fix didn't just disable lever B entirely.)
ha8c = fresh()
set_thermostat(ha8c, action="cooling")
gr8c = svc.ZONES["upstairs"]["rooms"]["Game Room"]
ha8c.states[gr8c["occupancy"]] = "on"
ha8c.states[gr8c["temp"]] = 77.0
for zn, zone in svc.ZONES.items():
    for rn, s in zone["rooms"].items():
        if rn == "Game Room":
            continue
        if s.get("occupancy"):
            ha8c.states[s["occupancy"]] = "off"
presence(ha8c)
check("T8 C: downstairs is fully VACANT (never occupied)",
      ha8c._zone_is_vacant("downstairs"))
got8c = ha8c._donor_cooler_by("downstairs", svc.PRIORITY_DONOR_COOLER_BY, False)
check("T8 C: vacant-zone donor requirement strictly relaxed (< base)",
      got8c < svc.PRIORITY_DONOR_COOLER_BY)
check("T8 C: relaxed requirement floored at ZONE_VACANCY_DONOR_MIN_COOLER_F",
      got8c >= svc.ZONE_VACANCY_DONOR_MIN_COOLER_F)
print(f"    vacant downstairs donor_cooler_by={got8c:.3f} "
      f"(base {svc.PRIORITY_DONOR_COOLER_BY}, floor "
      f"{svc.ZONE_VACANCY_DONOR_MIN_COOLER_F})")

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
