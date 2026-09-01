"""Smart Vent Controller for Flair vents.

Zones airflow by floor using room temperature, occupancy, and ecobee state.
Respects manual overrides. Proportional control (0/50/100%).
Backpressure-aware: never closes more than 60% of total vents.

Controls:
  input_boolean.vent_control_enabled  - master on/off
  input_select.vent_control_mode      - Auto / Manual / Cool Upstairs / Cool Downstairs
"""

import json
import math
import os
import re
import tempfile

import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta


# ── Zone / vent / sensor mapping ──────────────────────────────────────────────

ZONES = {
    "upstairs": {
        "rooms": {
            "Guest Bedroom 1": {
                "temp": "sensor.guest_bedroom_1_temperature",
                "occupancy": "binary_sensor.guest_bedroom_1_occupancy",
                "vents": [
                    "cover.guest_bedroom_1_8d6d_vent",
                    "cover.guest_bedroom_1_8136_vent",
                ],
            },
            "Guest Bedroom 2": {
                "temp": "sensor.guest_bedroom_2_temperature",
                "occupancy": "binary_sensor.guest_bedroom_2_occupancy",
                "vents": [
                    "cover.guest_bedroom_2_1ec7_vent_2",
                ],
            },
            "Game Room": {
                "temp": "sensor.game_room_temperature",
                "occupancy": "binary_sensor.game_room_occupancy",
                "vents": [
                    "cover.game_room_889a_vent",
                    "cover.game_room_89ae_vent",
                    "cover.game_room_0c83_vent",
                ],
            },
            "Cat Room": {
                "temp": "sensor.cat_room_temperature",
                "occupancy": "binary_sensor.cat_room_occupancy",
                "vents": [
                    "cover.cat_room_b58e_vent",
                    "cover.cat_room_3075_vent",
                ],
            },
            "Guest Bathroom": {
                "temp": "sensor.guest_bathroom_temperature",
                "occupancy": "binary_sensor.guest_bathroom_occupancy",
                "vents": [
                    "cover.guest_bathroom_e5a3_vent",
                ],
                # No dedicated return duct + closed door + 2nd story: cold supply
                # air pools at the floor and leaks out the door gap instead of
                # mixing to the ceiling where the sensor sits. Over-delivering
                # (100%) wastes cold air the room can't circulate and causes the
                # controller to cycle 0<->100 as the stratified sensor oscillates.
                # Cap at 50% so the room gets steady half-flow instead of slamming
                # open/closed. The 50% position is physically held by the Flair
                # damper (verified 2026-07-15).
                "max_vent_pct": 50,
            },
        },
    },
    "downstairs": {
        "rooms": {
            "Main Bedroom": {
                "temp": "sensor.main_bedroom_temperature",
                "occupancy": "binary_sensor.main_bedroom_occupancy",
                "vents": [
                    "cover.main_bedroom_883f_vent_2",
                    "cover.main_bedroom_a96d_vent_2",
                    "cover.main_bedroom_5c2b_vent_2",
                ],
                # donor_only: this room can be a DONOR (throttled to redirect
                # flow to a hotter room) but never a BENEFICIARY (it never
                # steals airflow from other rooms for itself). Main Bedroom
                # is typically unoccupied during the day; even if someone
                # walks in and it warms up, we don't want it throttling
                # occupied rooms (Living Room, Kitchen, etc.) to feed itself.
                # Its own vent positions still follow normal temp/occupancy
                # logic. 2026-07-16.
                "donor_only": True,
            },
            "Main Bathroom": {
                "temp": "sensor.main_bathroom_temperature",
                "occupancy": "binary_sensor.main_bathroom_occupancy",
                "vents": [
                    "cover.main_bathroom_f586_vent_2",
                ],
                # Vent f586 is effectively disconnected — weakest battery
                # (2.42V), worst RSSI (-80), and its duct temp reads ~98°F
                # (stagnant attic air, not supply). Hard-cap to 0% so the
                # controller never commands it open, regardless of room temp
                # or HVAC state. Reuses the max_vent_pct clamp (applied at the
                # single set-vents chokepoint, so Auto/Manual/priority/
                # fan-assist/equalize all respect it). 2026-07-16.
                "max_vent_pct": 0,
            },
            "Hallway": {
                "temp": "sensor.hallway_temperature",
                "occupancy": None,
                "vents": [
                    "cover.hallway_907e_vent_2",
                ],
                # donor_only: the hallway/foyer is a pass-through space, not
                # a destination room. It can be a donor (throttled to feed a
                # hotter occupied room) but never a beneficiary (it never
                # steals airflow from occupied rooms for itself). Its vent
                # still opens/closes normally based on its own temp. 2026-07-16.
                "donor_only": True,
            },
            "Living Room": {
                "temp": "sensor.living_room_temperature",
                "occupancy": "binary_sensor.living_room_occupancy",
                "vents": [
                    "cover.living_room_fc56_vent_2",
                    "cover.living_room_5d8e_vent_2",
                ],
            },
            "Kitchen": {
                "temp": "sensor.kitchen_temperature",
                "occupancy": None,
                "vents": [
                    "cover.kitchen_d124_vent_2",
                ],
            },
            "Dining Room": {
                "temp": "sensor.dining_room_temperature",
                "occupancy": "binary_sensor.dining_room_occupancy",
                "vents": [
                    "cover.dining_room_7a28_vent_2",
                ],
            },
            "Laundry Room": {
                "temp": "sensor.laundry_room_temperature",
                "occupancy": "binary_sensor.laundry_room_occupancy",
                "vents": [
                    "cover.laundry_room_d189_vent_2",
                ],
                # donor_only: occupancy here is a noisy signal, not a meaningful
                # one — people are in and out in ~10 min bursts (grabbing
                # laundry), unlike a bedroom or living room where occupancy
                # means someone is actually settled in the space. Treating a
                # transient occupancy blip as demand would let the room
                # compete for airflow it doesn't really need. Laundry Room can
                # still be a DONOR (throttled to feed a hotter occupied room)
                # but never a BENEFICIARY (never steals airflow for itself).
                # Its own vent position still follows normal temp/occupancy
                # logic. 2026-07-26.
                "donor_only": True,
            },
        },
    },
    "basement": {
        "rooms": {
            "Basement": {
                "temp": "sensor.7wq7_temperature",
                "occupancy": "binary_sensor.7wq7_occupancy",
                "vents": [
                    "cover.basement_4d79_vent",
                ],
            },
        },
    },
}

def _get_all_vents():
    """Helper to collect all vent entity IDs from the zone config."""
    vents = []
    for zone in ZONES.values():
        for room in zone["rooms"].values():
            vents.extend(room.get("vents", []))
    return vents

THERMOSTAT = "climate.ecobee_thermostat"
MODE_SELECT = "input_select.vent_control_mode"
ENABLED_SWITCH = "input_boolean.vent_control_enabled"

# Liveness heartbeat: the control loop stamps this sensor every cycle (even when
# disabled). An external cron watchdog alerts if it goes stale, catching the
# "app silently died / stopped looping" failure that originally went unnoticed.
HEARTBEAT_ENTITY = "sensor.smart_vent_controller_heartbeat"
# Summary sensor for the delivery/capacity handicap (achieved-cooling-rate axis).
DELIVERY_PENALTY_ENTITY = "sensor.smart_vent_delivery_handicap"
# Observability for the zone-presence contention axis: publishes each zone's
# occupied/vacant state + last-occupied age + the computed contention for the
# current cycle, so the deploy dispatch / Grafana can see the fix in action.
ZONE_PRESENCE_ENTITY = "sensor.smart_vent_zone_presence"

# Backpressure: never close more than this fraction of total vents.
MAX_CLOSED_RATIO = 0.60
# HARD structural ceiling — never close more than this even when the coil
# temp says we could. Static pressure at very high closure ratios spikes
# before the suction sensor can react (it's a lagging signal), risking ECM
# blower over-ramp, duct leakage, and choked airflow. Feedback lets us be
# aggressive WITHIN a physically sane envelope, not remove the envelope.
MAX_CLOSED_RATIO_HARD_CEILING = 0.80

# ── Dynamic backpressure (coil-temperature feedback) ────────────────────────
# A suction-line temp sensor (sensor.kitchen_water_temp_sensor, strapped to
# the vapor line at the indoor coil outlet) gives a direct proxy for coil
# surface temp in cooling mode. Coil ~40-42°F normal; suction picks up a few
# °F superheat → ~45-48°F normal. Below ~38°F suction the coil is at/near
# freezing (TXV superheat masks it, so by the time suction reads 35°F the
# coil is already icing). We scale the max-closed ratio by this signal so we
# can be aggressive when the coil is healthy and back off automatically as it
# approaches freeze — replacing the blind static 60% cap with measured data.
#
# Threshold ladder (°F suction line, cooling mode only):
#   >= 50°F  → 80% (hard ceiling)  — coil very healthy, push hard
#   45-50°F  → 70%                 — normal, still aggressive
#   42-45°F  → 60%                 — backing off (old static default)
#   38-42°F  → 40%                 — coil getting cold, open up
#   < 38°F   → EMERGENCY (latched) — force-open vents, freeze imminent
#
# Hysteresis: 2°F between bands (a band's lower edge must be cleared by 2°F
# before stepping back UP to a more aggressive ratio, so a 46°F reading
# oscillating with 44°F doesn't toggle 70%↔60%). Dwell: minimum 4 min
# between ratio changes (suction responds to vent changes with minutes of
# lag). Emergency is LATCHED — once tripped, requires sustained recovery
# above 44°F for 5 min before releasing.
#
# Gates (all must hold to use the dynamic ratio; else fall back to static 60%):
#   1. hvac_action == "cooling" (not heating/idle — suction reads warm ambient
#      when the compressor is off, which would falsely trigger aggressive mode)
#   2. compressor has been running >= COIL_FEEDBACK_MIN_RUNTIME seconds (avoids
#      startup transient where suction is still settling / residual heat)
#   3. sensor state is numeric and last_updated within COIL_FEEDBACK_STALE_SEC
#   4. sensor is not stuck (some variation over the staleness window — a frozen
#      reading is the worst-case failure, masking a freezing coil)
COIL_TEMP_SENSOR = "sensor.ac_suction_line_temp"
COIL_FEEDBACK_MIN_RUNTIME = 480      # 8 min compressor-on before trusting aggressive ratios
COIL_FEEDBACK_STALE_SEC = 300        # sensor older than 5 min → fall back to static
COIL_FEEDBACK_STUCK_WINDOW = 900     # 15 min: if zero variation over this, sensor is stuck
COIL_FEEDBACK_DWELL_SEC = 240        # min 4 min between ratio changes
COIL_EMERGENCY_THRESHOLD = 38.0      # °F suction → force-open (latched)
COIL_EMERGENCY_RECOVER = 44.0        # °F suction sustained 5 min → release latch
COIL_EMERGENCY_RECOVER_SEC = 300
# (ratio, lower_edge_with_hysteresis) — stepped, aggressive→conservative
COIL_RATIO_BANDS = [
    (0.80, 50.0),   # suction >= 50°F (with 2°F hysteresis on re-entry)
    (0.70, 45.0),   # 45-50°F
    (0.60, 42.0),   # 42-45°F
    (0.40, 38.0),   # 38-42°F
]

# How far a room temp can be from setpoint before we react (°F)
DEADBAND = 1.0

# Ignore occupancy when a room is this far over setpoint (°F). ecobee remote
# sensors use PIR motion detection — a room with nobody moving in it reads
# unoccupied even if it's 80°F and needs cooling. When a room is this hot,
# treat it as a beneficiary regardless of occupancy. The house is imbalanced
# (upstairs 5-8°F above main floor) and leaving hot rooms uncooled because
# nobody is standing in them makes the imbalance worse.
OCCUPANCY_OVERRIDE_OVER = 3.0

# ── Per-floor unoccupied drift targets (cooling season, data-driven) ───────
# Empirical targets from 3 days of cooling-cycle drift data (Jul 13-16):
#   - Downstairs rooms already hold +1-2°F (Living Room p50 +1.6, Dining +0.3).
#     Main Bedroom is overcooled (p50 -0.6) — we can sacrifice it harder.
#   - Upstairs rooms run much hotter (GB1 p50 +4.8, Game Room +3.7, GB2 +2.3).
#     The duct/solar physics there can't meet downstairs targets, so we accept
#     more drift and instead sacrifice empty upstairs rooms to feed occupied ones.
# These control two things in _auto_calculate:
#   1. When an unoccupied room gets throttled to 50% (start sacrificing its
#      airflow to occupied rooms) — the throttle point, in °F over setpoint.
#   2. When an unoccupied room gets full 100% airflow despite being empty
#      (the per-floor hot-override; below OCCUPANCY_OVERRIDE_OVER only, which
#      remains the absolute floor for any room).
# Occupied rooms always get 100% at +1°F (DEADBAND) regardless of floor.
UNOCC_THROTTLE_DOWNSTAIRS = 2.0   # empty 1F room -> 50% (was +1F)
UNOCC_THROTTLE_UPSTAIRS   = 3.0   # empty 2F room -> 50% (was +1F)
UNOCC_HOT_OVERRIDE_DOWN   = 3.0   # empty 1F room -> 100% at +3F
UNOCC_HOT_OVERRIDE_UP     = 5.0   # empty 2F room -> 100% at +5F (solar load)

# ── Per-floor OCCUPIED deadband (cooling season, data-driven 2026-07-17) ───
# 96h floor-average comparison: downstairs holds a much tighter band than
# upstairs (mean gap 1.6F; night gap ~1.2F, day gap ~2.0F, widening to 3-5F
# during peak sun hours). Before this, ANY occupied room >DEADBAND (1°F)
# over setpoint locked to 100% and became donor-immune, regardless of floor
# — so an occupied downstairs room a fraction of a degree over setpoint was
# treated exactly like an occupied upstairs room fighting real solar/duct
# load. Downstairs' lower heat load means it drifts back on its own; it
# doesn't need vents open "as long or as wide" as upstairs to stay
# comfortable. Occupied downstairs now tolerates more real deviation before
# pinning to 100%; occupied upstairs keeps the original tight (protective)
# deadband (numerically equal to DEADBAND, so upstairs behavior is
# unchanged).
OCC_DEADBAND_DOWNSTAIRS = 1.5
OCC_DEADBAND_UPSTAIRS   = 1.0

# Cross-floor donor threshold: downstairs rooms need less proven per-cycle
# margin to qualify as a donor to an UPSTAIRS beneficiary than the flat
# PRIORITY_DONOR_COOLER_BY requires — downstairs is empirically cooler on
# average (same 7/17 data), so we don't need to wait for a big instantaneous
# gap to trust it has spare cold air to give up.
PRIORITY_DONOR_COOLER_BY_CROSS_FLOOR = 0.75

# Hysteresis: once a vent opens, the zone must drop this far BELOW the
# close threshold before we actually close it. Prevents flapping at setpoint.
HYSTERESIS = 0.5

# Cycle interval in seconds
CYCLE_INTERVAL = 120

# After a manual override via HA UI, hold that position for this long
MANUAL_HOLD_MINUTES = 60

# Grace period (seconds) before a tilt-position mismatch is trusted as a real
# manual override. Flair vents are motorized dampers that take several
# seconds to travel between positions and can report TRANSIENT intermediate
# tilt values while still executing OUR OWN just-issued command (e.g.
# reporting 45% while coasting from 100% down to a commanded 0%). Latching
# the 60-minute hold on the FIRST mismatched reading treats that transit
# state as user intervention, silently locking the vent at whatever
# intermediate position it happened to report — which then defeats every
# subsequent redirection cycle for an hour. Confirmed 2026-07-23: 8 vents
# were simultaneously flagged "manual override" within 1.5s of each other
# right after a bulk close command — physically impossible for 8 people to
# touch 8 vents in 1.5s; that was the automation racing its own command.
# Instead of latching immediately, wait MANUAL_OVERRIDE_CONFIRM_SEC and
# re-read the position: if it still doesn't match what we last commanded,
# it's a real override (a human held/moved it, or physically blocked it)
# and the hold is applied then. If it settled to our commanded value in the
# meantime, the mismatch was just transit noise and no hold is applied.
MANUAL_OVERRIDE_CONFIRM_SEC = 8

# Heat rises: upstairs gets this bonus (°F) added to its effective diff when
# cooling. A 2°F bonus means upstairs is treated as 2° hotter than measured,
# so it wins priority over downstairs when both floors are above setpoint.
# Reversed for heating: downstairs gets the bonus (cold sinks).
UPSTAIRS_HEAT_RISE_BONUS = 2.0

# ── Priority-room airflow concentration ───────────────────────────────────────
# ANY room can become disadvantaged: end of a long supply run, sun-facing
# (solar gain), a poorly insulated duct delivering warm supply air, or just a
# transient hot spot. Guest Bedroom 1 is today's known worst case (end-of-run,
# west sun, ~6°F warm supply) but this logic is GENERAL — every room is eligible
# for priority treatment whenever it's the one struggling. GB1 is not special-
# cased; it simply trips these thresholds most often right now.
#
# Scoring alone can't fix a struggling room: when several rooms are above the
# cool setpoint they all score "needs airflow" and all sit at 100%, so no single
# room gets a *larger share* of the blower's output. The only lever that moves
# more CFM to a hot room is throttling OTHER, cooler rooms to redirect flow.
#
# How it generalizes to all rooms:
#   - Every occupied room over its activation margin is a "beneficiary".
#   - Beneficiaries are helped worst-first (largest overshoot gets first pick).
#   - A beneficiary is NEVER a donor — we don't steal from a room that's itself
#     struggling. Donors are only rooms that are comfortably cooler.
#   - If the whole house is equally hot there are no donors and it's a no-op
#     (correct: there's no banked cold air to redistribute).
#   - The backpressure pass still runs afterward as the final safety net.
#
# Activation margin (°F over the cool setpoint) is DERIVED, not hand-tuned. A
# room with a warm supply-air handicap should react earlier — we measure that
# handicap directly from the Flair duct (supply-air) temperature sensors instead
# of maintaining a per-room table.
#
# Each cooling cycle we compute every room's "supply penalty" = how many °F
# warmer its supply air arrives vs. the coldest duct in the house (the best the
# system can deliver). A room at the end of a long/uninsulated run reads a large
# penalty automatically; a well-served room reads ~0. The penalty is smoothed
# (EMA) so a transient throttled-vent reading doesn't jerk the margins around.
#
#   effective_margin = PRIORITY_MARGIN_BASE
#                      - PRIORITY_PENALTY_GAIN * smoothed_penalty * hot_factor
#   clamped to [PRIORITY_MARGIN_MIN, PRIORITY_MARGIN_BASE]
#
# Lower margin = engages earlier. The floor is 0.0, NOT negative: a bad duct
# should make a room react the instant it goes OVER setpoint, but never while
# it's still comfortable. This is what lets shade/occupancy win — a room on the
# shady, lightly-used side of the house (e.g. a bathroom with a terrible duct)
# simply never trips, because it rarely gets above setpoint while occupied.
# No room is ever favored while below the cool setpoint (the pre-cool window
# only tightens the margin toward 0, it does not go negative). The duct handicap
# controls how EARLY a room reacts once it's over setpoint, not whether a cool
# room gets favored for no reason.
PRIORITY_MARGIN_BASE = 1.5      # margin for a zero-penalty (well-served) room
PRIORITY_MARGIN_MIN = 0.0       # most aggressive margin: react at setpoint, not before
PRIORITY_PENALTY_GAIN = 0.30    # °F margin reduction per °F of supply penalty
PRIORITY_PENALTY_EMA = 0.30     # smoothing factor for the per-room penalty
PRIORITY_PENALTY_MIN_SAMPLE = 1.0  # ignore penalties smaller than this (noise)
# Only sample a duct's temperature when its vent is at least this open — a
# throttled vent reads warm because air isn't flowing, which is not a real
# supply handicap. Prevents a feedback loop (throttle -> looks handicapped ->
# gets favored -> opens -> penalty corrects).
DUCT_SAMPLE_MIN_TILT = 100

# Outdoor temperature makes the handicap matter more: on a hot day a warm-supply
# room falls behind faster, so we amplify its penalty. hot_factor ramps from 1.0
# at HOT_BASE up to (1 + (outdoor-HOT_BASE)/HOT_SPAN). Read from the weather
# entity; if unavailable, hot_factor = 1.0 (no amplification).
WEATHER_ENTITY = "weather.forecast_home"
HOT_BASE_F = 80.0
HOT_SPAN_F = 30.0               # +1.0 to the factor per 30°F above HOT_BASE
HOT_FACTOR_MAX = 2.0
# Heating mirror: cold outside amplifies the heating supply handicap.
COLD_BASE_F = 45.0             # below this, the heating handicap starts ramping
COLD_SPAN_F = 30.0            # +1.0 to the factor per 30°F below COLD_BASE

# Optional manual escape hatch: only used if you ever need to pin a specific
# room's margin and override the measured value. Normally empty.
PRIORITY_MARGIN_OVERRIDES = {
    # ("zone", "Room Name"): margin_f
}
# A donor room qualifies only if it is at least this many °F COOLER than the
# beneficiary room itself. Measured relative to the beneficiary (not the absolute
# setpoint) on purpose: when the setpoint is aggressive the whole house can sit
# above it, but a room 1.5°F+ cooler than the struggling room still has enough
# margin to give up some airflow. Donors are throttled to 50% (never closed), so
# they keep getting half their flow and won't run away from setpoint.
PRIORITY_DONOR_COOLER_BY = 1.5
# Throttle position for donor rooms (Flair vents are 0/50/100 only).
PRIORITY_DONOR_POS = 50
# Never throttle more than this many donor rooms per beneficiary room.
# Raised from 4 to 8 — with dynamic backpressure (coil-temp feedback) now
# allowing up to 80% of vents closed, we can concentrate airflow harder on
# the worst occupied room. The backpressure safety net still caps total
# closures, so this just lets the priority pass find more donors.
PRIORITY_MAX_DONORS = 8
# Escalation: when a beneficiary is THIS far over the cool setpoint, it's not
# just lagging, it's losing. Throttle donors all the way to 0% (closed) instead
# of 50% to dump maximum CFM into it. The backpressure pass still caps total
# closures at MAX_CLOSED_RATIO, so this can't choke the system.
PRIORITY_ESCALATE_OVER = 3.0
PRIORITY_DONOR_POS_ESCALATED = 0
# Per-room escalation override: lets a specific room escalate to full (0%)
# donor throttling sooner than the flat PRIORITY_ESCALATE_OVER, without
# changing behavior for every other room. Game Room runs hot most cycles
# (2026-08-31, user asked to prioritize it further) — escalate at 1.5F over
# setpoint instead of waiting for 3.0F, so it starts pulling maximum donor
# CFM much earlier in an overshoot.
PRIORITY_ESCALATE_OVERRIDES = {
    ("upstairs", "Game Room"): 1.5,
}

# ── Delivery / capacity handicap (achieved-cooling-rate axis) ──────────────────
# The SECOND handicap axis, orthogonal to the supply-air penalty above.
#
# _update_supply_penalties catches rooms whose SUPPLY air is ineffective (warm
# duct on a long/uninsulated run) — that was GB1. But a room can have perfectly
# good supply air, sit wide open, and STILL never reach setpoint because it
# can't move enough air (an undersized / single vent) or carries a large
# internal or solar load. GB2 is exactly this: its duct is the COLDEST upstairs
# (supply penalty ~0, so the supply mechanism correctly stays silent) yet it's
# the most-often-hottest room — it has one vent and ~90% occupancy. That
# handicap is invisible to any supply-TEMPERATURE measurement; it only shows up
# in the room's achieved RATE of approach to setpoint.
#
# We measure that rate directly. A room that is (a) occupied, (b) past the
# deadband in the wrong direction, (c) already receiving good supply air (low
# supply penalty — so we're not double-counting the GB1 axis), and (d) wide open
# (we're already giving it everything), yet is NOT closing the gap, has a
# delivery/capacity handicap. We accrue an EMA penalty for it, smoothed like the
# supply penalty. That penalty does two things:
#   1. Lowers the room's activation margin (it becomes a beneficiary earlier).
#   2. Past DELIVERY_ESCALATE_PENALTY, forces donor ESCALATION (throttle donors
#      to 0% instead of 50%) so the controller dumps maximum CFM at it — the
#      only software lever left for a capacity-limited room. Backpressure still
#      caps total closures, so this can't choke the system.
# Self-correcting: once the room finally moves toward setpoint the rate goes
# positive, the stuck condition clears, and the penalty decays back to zero.
# Like the supply penalty, this is MEASURED per room, not a hand-tuned table, so
# it generalizes to every room (capacity, load, or solar) on one axis.
DELIVERY_STUCK_RATE = 0.05      # °F/min toward setpoint; below this while maxed = stuck
DELIVERY_PENALTY_EMA = 0.25     # smoothing (a touch slower than supply — noisier signal)
DELIVERY_PENALTY_MAX = 4.0      # cap per-sample stuck contribution (°F) so one reading can't dominate
DELIVERY_MIN_DT_MIN = 0.5       # ignore intervals shorter than this (sensor noise)
DELIVERY_MAX_DT_MIN = 10.0      # ignore long gaps (restart / sensor dropout) — rate is meaningless
DELIVERY_MARGIN_GAIN = 0.30     # °F margin reduction per °F of delivery penalty
DELIVERY_ESCALATE_PENALTY = 1.5  # delivery penalty above this forces donor escalation

# ── Zone-presence contention (measured axis) ─────────────────────────────────
# The production bug (2026-08-31): with everyone upstairs and the Game Room at
# 77°F while the ecobee read a whole-house 73-74°F average, the owner dropped the
# cool setpoint 73->70°F to force the compressor on. The low setpoint pushed
# several completely UNOCCUPIED downstairs rooms past the absolute
# OCCUPANCY_OVERRIDE_OVER=3.0 threshold, which overrode the occupancy gate
# entirely: they became protected beneficiaries pinned to 100% and — critically —
# could NEVER be selected as a DONOR for the genuinely occupied, badly overheated
# Game Room. Those empty rooms locked in at 100% and competed with Game Room for
# limited compressor CFM, producing "Priority Game Room struggling but no donor
# rooms" every cycle.
#
# The fix is a NEW measured axis derived purely from real sensors every cycle,
# following the established pattern of _update_supply_penalties /
# _update_delivery_penalties / _room_margin: "zone presence contention".
#
#   * _update_zone_presence() stamps each zone's last occupied time from its
#     rooms' PIR occupancy sensors. A zone counts OCCUPIED if ANY of its rooms
#     read "on" within ZONE_PRESENCE_HOLD_MIN minutes (debounce so a transient
#     PIR false-negative doesn't instantly demote a zone).
#   * _zone_contention(zone, heating) = a [0,1] factor for how badly some OTHER,
#     OCCUPIED zone's occupants need air right now (the max room excess-over-
#     margin among occupied zones that aren't `zone`, saturated at 1.0 once that
#     excess reaches ZONE_CONTENTION_SPAN_F).
#   * Lever A (_effective_occupancy_override): when a room's OWN zone is vacant,
#     its protected-beneficiary threshold is raised above the bare
#     OCCUPANCY_OVERRIDE_OVER by ZONE_VACANCY_OVERRIDE_BONUS_F * contention, so
#     an empty room must be genuinely hot before it can re-lock into 100% (and
#     out of donor eligibility) while another floor's occupants are suffering.
#     Capped at ZONE_VACANCY_OVERRIDE_CEILING_F so a truly baking room is NEVER
#     starved. Hysteresis: a demoted room must exceed
#     raised + ZONE_VACANCY_OVERRIDE_HYST_F to re-promote, and a protected room
#     must fall below raised to demote, so a vacant room that donates air -> heats
#     up -> crosses the threshold -> cools -> donates again doesn't flap its
#     damper every cycle. _zone_vacancy_demoted (a set of (zone, room) keys)
#     tracks the per-room demotion state; entries clear when the zone stops being
#     vacant.
#   * Lever B (_donor_cooler_by): donor eligibility relaxes for rooms in VACANT
#     zones, proportional to contention — the "must be cooler by" requirement is
#     waived fractionally (ZONE_VACANCY_DONOR_RELAX) but floored at
#     ZONE_VACANCY_DONOR_MIN_COOLER_F so we NEVER pull air from a room that isn't
#     genuinely more comfortable than the beneficiary (thermodynamic guard).
#
# Both levers are applied in BOTH the priority pass (_apply_priority_rooms) and
# the fan-assist pass (_apply_fan_assist) via two shared helpers, so they can't
# drift out of sync (the recurring two-pass bug class in this file).
#
# Design guarantee: when NO other zone has an occupied room past its margin,
# _zone_contention returns EXACTLY 0.0, both levers collapse to identity, and
# behavior is byte-identical to today. A solar-baked empty room in a fully empty
# house still gets airflow exactly as it does now.
ZONE_PRESENCE_HOLD_MIN          = 25.0   # a zone counts OCCUPIED if any of its rooms read occupancy "on" within this many minutes
ZONE_CONTENTION_SPAN_F          = 3.0    # occupied-zone excess-over-margin (F) that saturates the contention factor at 1.0
ZONE_VACANCY_OVERRIDE_BONUS_F   = 3.0    # how much a VACANT zone's self-protect threshold rises at full contention
ZONE_VACANCY_OVERRIDE_CEILING_F = 6.5    # hard bake-protection ceiling: past this a vacant room is helped regardless of contention
ZONE_VACANCY_OVERRIDE_HYST_F    = 0.5    # hysteresis band so a demoted room doesn't chatter around the raised threshold
ZONE_VACANCY_DONOR_RELAX        = 0.75   # fraction of the donor "must be cooler by" requirement waived at full contention
ZONE_VACANCY_DONOR_MIN_COOLER_F = 0.25   # floor: never pull air from a room that isn't at least this much more comfortable than the beneficiary

# ── Setpoint nudge (the TRIGGER axis — make the compressor escalate) ─────────
# The zone-presence-contention fix solves AIRFLOW REDISTRIBUTION once the
# compressor runs. This solves the TRIGGER problem: the ecobee's
# climate.ecobee_thermostat.current_temperature is a FLAT AVERAGE across all 14
# remote sensors, so a single hot room (Game Room at 77F) can sit far above its
# cool setpoint while the whole-house average stays comfortably under the
# ecobee's own call-for-cooling thresholds — the compressor simply never
# escalates to stage 2, and the only lever that reaches the thermostat is moving
# the SETPOINT the ecobee sees (the stage-2 differential is manual-only on the
# physical unit, not API-settable). Tonight the owner had to hand-drop the cool
# setpoint 73->71->70 to force the compressor on.
#
# Mechanism: every cycle we already compute each occupied room's `off_target`
# (degrees past the active setpoint in the unhelpful direction, sign-aware for
# heat vs cool) and `_room_margin(key, heating)` (that room's derived activation
# margin, lowered by measured supply-air and delivery handicaps). Their
# difference — `worst_excess = max over OCCUPIED rooms of (off_target - margin)`
# — is exactly the quantity _zone_contention already computes (measured axis,
# NOT a hardcoded schedule), so we reuse that same measured idiom to drive the
# setpoint. When the worst occupied excess clears the engage threshold we write
# a temporary hold via the existing, verified ecobee_enhanced service family
# (the SAME family fan-assist already uses), dragging both setpoints so the
# compressor sees a genuine call and escalates. Fully heating/cooling symmetric
# (cooling: drop the cool setpoint; heating: raise the heat setpoint).
#
# Hard-won lesson reused here: ALL service calls are fire-and-forget with
# callback=self._service_call_done (see _set_vent — a blocking call_service
# froze this app's single pinned thread for ~4.5h once).
SETPOINT_NUDGE_ENGAGE_F   = 1.5   # worst_excess at/above this engages a nudge
SETPOINT_NUDGE_RELEASE_F  = 0.5   # worst_excess at/below this releases it (hysteresis band; MUST be < ENGAGE)
SETPOINT_NUDGE_GAIN       = 0.5   # degrees of setpoint nudge per degree of worst_excess
SETPOINT_NUDGE_MAX_F      = 3.0   # hard cap on how far we may ever move the user's setpoint
SETPOINT_NUDGE_STEP_F     = 0.5   # ecobee setpoint granularity; quantize to this
SETPOINT_NUDGE_DWELL_SEC  = 600   # min seconds between setpoint writes (>= compressor min-ON 10min; prevents fighting the ecobee's own staging)
SETPOINT_NUDGE_CONFIRM_SEC= 420   # readback mismatch must persist this long before it's believed (ecobee cloud poll floor is 3 min)
SETPOINT_NUDGE_TOLERANCE_F= 0.2   # readback match tolerance
SETPOINT_HEATCOOL_MIN_DELTA_F = 6.0  # ecobee heatCoolMinDelta, see TRAP 1 below

# ── Setpoint-nudge ownership persistence (restart-amnesia / baseline-ratchet fix,
#    added 2026-09-01) ─────────────────────────────────────────────────────────
# The ratchet: the restarted app has no memory of its OWN leftover nudge, so the
# ownership rule's value-match ("readback differs from what we commanded ->
# user changed it -> adopt as the new baseline") faithfully adopts the app's own
# residue as user intent and then nudges one STEP further. Every restart during
# an active nudge ratchets: 72 -> 66 -> 63 -> ...
#
# The fix is to survive restarts with the ownership record. We deliberately use
# a plain ATOMIC JSON FILE, not an HA input_text entity:
#   - an input_text entity can be unavailable/racy exactly when initialize()
#     runs during an AppDaemon/Core restart (the critical moment),
#   - input_text caps content at 255 chars,
#   - it is user-editable in the HA UI (and thus a source of state corruption).
# The file is written via a temp file + os.replace(), so a reader never sees a
# half-written record (atomic on POSIX, which includes the addon container).
# Path: derived from the app's own module path (__file__), which is deployed into
# the AppDaemon addon's writable /addon_configs/a0d7b954_appdaemon/apps/ dir (see
# the SCP target in the smart-vent-controller skill) — so the file travels with
# the app and always lands somewhere valid WITHOUT a hardcoded host path.
# All I/O here is defensive (any read/write exception is caught and logged);
# a lost write is a degraded-but-safe condition -> one-cycle replay of the
# dead-man's-switch hold, never a crash of initialize()/control_loop.
NUDGE_STATE_FILENAME = "smart_vent_controller_nudge_state.json"
# Timestamp the command (as ISO-8601 in UTC) when we persist, so a restore can
# still evaluate whether the persisted CONFIRM window from the command time is open.
NUDGE_STATE_VERSION = 1

# ── Fan-assist redistribution (the thermostat blind-spot workaround) ───────────
# A single hallway thermostat goes idle when the HOUSE AVERAGE is satisfied, even
# while an individual room is still hot — that's the core reason a disadvantaged
# room bakes. But when the AC has been running, other rooms (basement, bathrooms,
# north side) bank real cold air. This pass force-runs the air handler fan (no
# compressor), opens the hot room, and chokes the cold rooms — physically pushing
# banked cold air into the hot room with ZERO additional cooling cost. Applies to
# ANY occupied room, not just GB1. Engages only when:
#   - HVAC is idle/fan (NOT actively cooling — cooling is handled above),
#   - the room is occupied and >= FAN_ASSIST_OVER above the cool setpoint,
#   - at least one donor room is >= FAN_ASSIST_DONOR_COOLER_BY cooler than it
#     (i.e. there's actually cold air banked somewhere to move).
# Releases the fan back to auto the moment those stop being true, so it never
# just runs the blower for nothing.
FAN_ASSIST_OVER = 2.0
FAN_ASSIST_DONOR_COOLER_BY = 3.0
FAN_ENTITY = "climate.ecobee_thermostat"

# Dry-coil lockout. For several minutes after the compressor stops, the
# evaporator coil is still wet with condensate. Running the blower over it
# (fan-assist recirculation) re-evaporates that water back into the house.
#
# Set to 5 min (was 30): the bulk of coil condensate drains in the first 2-3
# min. With dedicated returns in every room, fan-assist is a proper circulation
# loop (return→supply), not just blowing warm duct air. The house has a 60%
# dehumidify target + standalone dehumidifiers to handle latent load, so a
# small amount of coil re-evaporation is acceptable in exchange for pushing
# banked cold air to hot rooms during the 10-15 min idle gaps.
#
# Monitor: if indoor RH climbs >2% between cycles, raise this. If upstairs
# stays hot with no fan-assist firing, lower it.
FAN_ASSIST_COIL_DRY_MIN = 5.0

# ── Predictive pre-cool ───────────────────────────────────────────────────────
# Sun-facing rooms start each afternoon already behind because the morning is
# spent NOT favoring them. During the pre-sun window, while cooling is happening
# anyway, bias ANY occupied room that's drifting up so it banks headroom before
# the solar load arrives. Lower activation margin (react earlier) during these
# local hours, applied house-wide.
PRECOOL_HOURS = range(10, 14)   # 10:00–13:59 local time
PRECOOL_MARGIN = 0.5            # engage priority pass when only this far over


class SmartVentController(hass.Hass):

    def initialize(self):
        self.log("Smart Vent Controller initializing...")

        # Track manual overrides: vent_entity -> expiry datetime
        self._manual_holds = {}

        # Track last-set positions to avoid redundant commands
        self._last_positions = {}

        # Track last zone-level positions for hysteresis
        self._last_zone_positions = {}

        # EMA-smoothed per-room supply penalty (°F warmer than the best duct),
        # measured from the Flair duct sensors. Drives each room's activation
        # margin so handicapped rooms react earlier without a hardcoded table.
        self._supply_penalty = {}

        # EMA-smoothed per-room DELIVERY penalty (the achieved-cooling-rate axis).
        # Accrues when a room is occupied, off-target, well-supplied, and wide
        # open yet still not closing the gap — i.e. a capacity/load handicap that
        # supply-air temperature cannot see (GB2's single vent). Drives the
        # margin like the supply penalty and forces donor escalation past
        # DELIVERY_ESCALATE_PENALTY. _delivery_last holds the prior (temp, time)
        # sample per room so we can compute the rate between control cycles.
        self._delivery_penalty = {}
        self._delivery_last = {}

        # Zone-presence contention state. _zone_last_occupied[zone] = datetime
        # when any room in that zone last read occupancy "on" (None = never
        # seen occupied since app start). _zone_occupied[zone] = bool for the
        # CURRENT cycle, recomputed every control loop by _update_zone_presence
        # (debounced by ZONE_PRESENCE_HOLD_MIN). _zone_vacancy_demoted is a set
        # of (zone, room) keys whose self-protect threshold is currently raised
        # because their zone is vacant under contention (hysteresis — see the
        # constants block); entries clear once the zone stops being vacant.
        self._zone_last_occupied = {}
        self._zone_occupied = {}
        self._zone_vacancy_demoted = set()

        # Setpoint-nudge ownership state (see the constants block + the state-
        # machine comment on _apply_setpoint_nudge). _sp_owned = True while WE
        # hold an active setpoint hold on the thermostat. _sp_baseline_* is the
        # LIVE setpoint we captured the moment we engaged (whatever the user's
        # own effective setpoint was — schedule or their manual hold) and is the
        # ONLY base any re-nudge may compute off of, so we can NEVER ratchet
        # away unboundedly. _sp_commanded_* is what we last wrote (the readback
        # we match against for ownership + pop-safety). _sp_last_write_ts gates
        # the dwell. _sp_mismatch_since lets a transient echo (the ecobee cloud
        # poll is up to 3 min behind a write) be distinguished from a real user
        # change after SETPOINT_NUDGE_CONFIRM_SEC. _sp_heating records the DIRECTION
        # of the nudge we own (True = heat, False = cool) captured at engage time:
        # when the system goes idle/fan there is no live axis to derive a direction
        # from, but to compare readback (and thus stay pop-safe) we must still know
        # which axis we moved. It is only meaningful while _sp_owned.
        self._sp_owned = False
        self._sp_commanded_cool = None
        self._sp_commanded_heat = None
        self._sp_baseline_cool = None
        self._sp_baseline_heat = None
        self._sp_last_write_ts = None
        self._sp_mismatch_since = None
        self._sp_heating = None

        # Persistence of the nudge-ownership record. _nudge_state_file is the
        # single source of truth for the state-file path; _nudge_persist_disable
        # lets offline tests point it at a temp file (and force-persist for the
        # write-ahead ordering assertion). _nudge_restore_pending is True after a
        # persisted record was loaded but not yet validated against the live
        # readback on the first control_loop cycle (see the comment on
        # _restore_nudge_ownership and control_loop — validation CANNOT safely
        # run inside initialize()). Derived from the app's own module path so it
        # lives in the addon's writable apps/ dir (see NUDGE_STATE_FILENAME).
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self._nudge_state_file = os.path.join(base_dir, NUDGE_STATE_FILENAME)
        self._nudge_persist_disable = False
        self._nudge_restore_pending = False

        # Re-adopt any persisted nudge-ownership record across an app restart.
        # Runs as early as possible so the ratchet cannot recur between
        # processes. The record's live-readback VALIDATION is deferred to the
        # first control_loop cycle (_nudge_restore_pending) — get_state() can be
        # unavailable/racy this early during an AppDaemon/Core restart, so a read
        # taken synchronously here could wrongly DISCARD a valid persisted nudge.
        # Defensive inside: any read/allocation exception is caught and logged.
        self._restore_nudge_ownership()

        # Dry-coil lockout tracking. _cooling_ended_at is the timestamp the
        # compressor last transitioned out of "cooling"; None while actively
        # cooling (or if we've never seen a cooling cycle this run). Used by
        # _apply_fan_assist to suppress recirculation over a still-wet coil.
        self._cooling_ended_at = None
        self._last_hvac_action = None

        # Dynamic-backpressure state (coil-temp feedback). See
        # _coil_temp_for_backpressure and _apply_backpressure_rooms.
        # _cooling_started_at: when the compressor last entered cooling (for
        #   the min-runtime gate that suppresses aggressive ratios at startup).
        # _coil_ratio_current: the last dynamic ratio we applied (for dwell).
        # _coil_ratio_changed_at: when we last changed the ratio (dwell gate).
        # _coil_emergency_latched: True once suction dropped below
        #   COIL_EMERGENCY_THRESHOLD; stays latched until sustained recovery.
        # _coil_emergency_since: timestamp suction first rose above recover
        #   threshold (latch releases after COIL_EMERGENCY_RECOVER_SEC sustained).
        # _coil_sensor_fail_count: consecutive cycles the sensor was
        #   unavailable/stale/stuck (for throttling log noise).
        self._cooling_started_at = None
        self._coil_ratio_current = None
        self._coil_ratio_changed_at = None
        self._coil_emergency_latched = False
        self._coil_emergency_since = None
        self._coil_sensor_fail_count = 0

        # Run the control loop
        self.run_every(self.control_loop, "now+10", CYCLE_INTERVAL)

        # Listen for manual vent changes (user moved a vent in the UI)
        all_vents = _get_all_vents()
        for vent in all_vents:
            self.listen_state(self.on_vent_manual_change, vent,
                              attribute="current_tilt_position")

        # Listen for occupancy changes to react immediately
        for zone in ZONES.values():
            for _room_name, sensors in zone["rooms"].items():
                occ = sensors.get("occupancy")
                if occ:
                    self.listen_state(self.on_occupancy_change, occ)

        # Listen for mode changes to run immediately
        self.listen_state(self.on_mode_change, MODE_SELECT)
        self.listen_state(self.on_mode_change, ENABLED_SWITCH)

        self.log(f"Smart Vent Controller ready. {len(all_vents)} vents across "
                 f"{len(ZONES)} zones. Cycle every {CYCLE_INTERVAL}s.")

        # Stamp the heartbeat immediately so the sensor exists on startup and the
        # watchdog isn't tripped by the first-cycle delay after a restart.
        self._heartbeat()

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_vent_manual_change(self, entity, attribute, old, new, kwargs):
        """Detect when a user manually moves a vent (not us).

        Debounced with a STABLE double-confirmation: Flair vents are
        motorized dampers that take several seconds to travel, and the
        Flair cloud coordinator itself can report flapping/transient
        tilt values for well over MANUAL_OVERRIDE_CONFIRM_SEC while still
        settling after OUR OWN just-issued command (observed 2026-07-23:
        a vent commanded to 0% read 0, then 100, then 0 again across a
        ~15s window with no human or code touching it — a single delayed
        recheck still lands mid-flap and false-latches). Treating any
        single mismatched reading as a real override (the original bug)
        silently locks the vent from automated control for
        MANUAL_HOLD_MINUTES. Instead: on a mismatch, wait
        MANUAL_OVERRIDE_CONFIRM_SEC and look again. If it now agrees with
        what we commanded, drop it (was transit/coordinator noise). If it
        still disagrees, wait ONE MORE MANUAL_OVERRIDE_CONFIRM_SEC and
        check whether the reading has been STABLE (unchanged) across that
        second wait — only a value that both disagrees with our command
        AND has stopped moving is trusted as genuine user intervention or
        a truly stuck damper.
        """
        if entity in self._last_positions:
            # If we just set this, ignore the state callback
            if self._last_positions[entity] == new:
                return
        self.run_in(
            self._confirm_manual_override,
            MANUAL_OVERRIDE_CONFIRM_SEC,
            entity=entity,
            check=1,
        )

    def _confirm_manual_override(self, kwargs):
        """Re-check a suspected manual override after a confirm delay.

        check=1: first recheck. If it now matches our last command, drop
        it (transit/coordinator noise). If it still disagrees, schedule a
        SECOND recheck and remember this disagreeing value.
        check=2: second recheck. Only latch the hold if the position is
        BOTH still disagreeing with our last command AND unchanged since
        check 1 (i.e. it has actually settled somewhere else, not just
        still flapping) — that combination is what distinguishes a real
        override / stuck damper from ongoing coordinator noise.
        """
        entity = kwargs["entity"]
        expected = self._last_positions.get(entity)
        current = self.get_state(entity, attribute="current_tilt_position")

        if expected is not None and current == expected:
            return  # settled to our commanded value — was just transit noise

        if kwargs.get("check") == 1:
            self.run_in(
                self._confirm_manual_override,
                MANUAL_OVERRIDE_CONFIRM_SEC,
                entity=entity,
                check=2,
                first_seen=current,
            )
            return

        # check == 2: only trust it if unchanged since the first recheck.
        if current != kwargs.get("first_seen"):
            self.log(f"  Manual-override check unstable for {entity} "
                      f"({kwargs.get('first_seen')}% -> {current}%) — "
                      f"still settling, not latching yet")
            return

        self._manual_holds[entity] = datetime.now() + timedelta(
            minutes=MANUAL_HOLD_MINUTES
        )
        self.log(f"Manual override confirmed: {entity} -> {current}%, "
                 f"holding for {MANUAL_HOLD_MINUTES}min")

    def on_occupancy_change(self, entity, attribute, old, new, kwargs):
        """Run control loop immediately when someone enters/leaves a room."""
        if old != new and new in ("on", "off"):
            self.log(f"Occupancy change: {entity} -> {new}, running control loop")
            self.control_loop(None)

    def on_mode_change(self, entity, attribute, old, new, kwargs):
        """Run control loop immediately when mode or enabled changes."""
        self.log(f"Mode change: {entity} {old} -> {new}, running control loop")
        self.control_loop(None)

    # ── Main control loop ─────────────────────────────────────────────────────

    def control_loop(self, kwargs):
        """Main control loop — runs every CYCLE_INTERVAL seconds."""

        # Liveness heartbeat FIRST, before any early return, so an external
        # watchdog can tell "the app process is alive and looping" apart from
        # "the controller is disabled". This is the exact failure that bit us
        # originally: the app was effectively not running and nobody knew.
        self._heartbeat()

        # Check master switch
        enabled = self.get_state(ENABLED_SWITCH)
        if enabled != "on":
            return

        mode = self.get_state(MODE_SELECT)
        self.log(f"Control loop: mode={mode}")

        if mode == "Manual":
            # Don't touch anything
            return

        # Get thermostat state
        hvac_mode, hvac_action, target_cool, target_heat = self._get_thermostat_state()
        self.log(f"Thermostat: mode={hvac_mode}, action={hvac_action}, "
                 f"cool={target_cool}, heat={target_heat}")

        # Restart-amnesia guard: the FIRST cycle after initialize() may carry a
        # persisted setpoint-nudge ownership record loaded from disk. Re-adopt
        # it now, against the CURRENT live readback, BEFORE any pass below
        # (baseline-aware vent scoring, _apply_setpoint_nudge) can use _sp_owned.
        # Validation runs HERE, not in initialize(), because get_state() for the
        # thermostat can be unavailable/racy the instant the app starts during an
        # AppDaemon/Core restart — if it returned no setpoints initialize() would
        # see a None readback and wrongly discard a valid persisted nudge (the
        # exact amnesia the fix exists to prevent). By the time the first loop
        # runs (run_every schedules control_loop at now+10; initialize returns
        # long before that), the HA state is settled, so the readback here is
        # trustworthy. One code path, documented; see _restore_nudge_ownership.
        if self._nudge_restore_pending:
            self._nudge_restore_pending = False
            if getattr(self, "_sp_owned", False):
                # initialize() re-adopted ownership. Still corroborate against
                # the live readback (the persisted record may have gone stale
                # during the restart window) — discard on ANY mismatch/expiry.
                self._validate_restored_nudge(target_cool, target_heat)

        # Baseline-aware vent scoring (single source of truth). While a setpoint
        # nudge is actively held AND its readback matches what we commanded, vent
        # scoring references the USER's effective (pre-nudge) baseline setpoints
        # instead of the artificially nudged LIVE ones — the vents aim at how the
        # house should FEEL, while the compressor is separately hammered harder by
        # the nudge. Computed HERE once per cycle, on the nudge state from the
        # previous cycle (exactly the state the current cycle's vent decisions
        # should use), and passed to all three vent-scoring passes so they can
        # never drift apart (recurring-bug-class guard). When no nudge is trusted
        # live, _active_nudge_baseline returns None and these equal the LIVE
        # setpoints byte-for-byte. The nudge's own pass and delivery penalties
        # deliberately keep using the LIVE setpoints (see their call sites).
        _bl = self._active_nudge_baseline(target_cool, target_heat)
        if _bl:
            eff_cool, eff_heat = _bl
        else:
            eff_cool, eff_heat = target_cool, target_heat

        # Track the compressor cooling->idle transition for the dry-coil
        # lockout. Stamp the moment cooling stops; clear it while cooling so a
        # fresh cycle resets the drain timer. Read by _apply_fan_assist.
        if self._last_hvac_action == "cooling" and hvac_action != "cooling":
            self._cooling_ended_at = self.datetime()
        elif hvac_action == "cooling":
            self._cooling_ended_at = None
        self._last_hvac_action = hvac_action

        # Track cooling-cycle start for the dynamic-backpressure min-runtime
        # gate. Suction line reads warm ambient when the compressor is off, so
        # we hold the conservative static ratio until the compressor has run
        # long enough for the suction signal to be meaningful.
        if hvac_action == "cooling":
            if self._cooling_started_at is None:
                self._cooling_started_at = self.datetime()
        else:
            self._cooling_started_at = None
            # Release the emergency latch when cooling ends — no freeze risk
            # with the compressor off, and a fresh cycle should start clean.
            if self._coil_emergency_latched:
                self.log("Coil emergency latch released (cooling ended)")
            self._coil_emergency_latched = False
            self._coil_emergency_since = None

        # Refresh measured per-room supply penalties whenever air is moving;
        # duct temps are only meaningful with airflow. These drive each room's
        # activation margin (handicapped rooms react earlier) automatically. The
        # handicap is mode-correct: warmest-supply-wins when heating, coldest
        # when cooling. (Skip on "fan" — no conditioned air, so no real penalty.)
        if hvac_action in ("cooling", "heating"):
            self._update_supply_penalties(heating=(hvac_action == "heating"))

        # Second handicap axis: achieved-cooling-rate. Must run AFTER supply
        # penalties (it reads them to avoid double-counting the supply-air axis)
        # and BEFORE _apply_priority_rooms (which reads the delivery penalty for
        # both margin and escalation). Runs every cycle so the penalty decays
        # when the room recovers or HVAC goes idle.
        self._update_delivery_penalties(hvac_action, target_cool, target_heat)

        # Zone-presence contention (measured axis). Stamps each zone's last
        # occupied time and recomputes the per-zone occupied/vacant booleans for
        # this cycle. Must run BEFORE _auto_calculate / _apply_priority_rooms /
        # _apply_fan_assist, which read the contention-adjusted thresholds and
        # donor relaxation. Runs every cycle so the demotion state (and the
        # published sensor) stays current.
        self._update_zone_presence()

        # Calculate desired positions.
        # room_positions: {(zone_name, room_name): position}
        room_positions = {}

        if mode == "Cool Upstairs":
            for rn in ZONES["upstairs"]["rooms"]:
                room_positions[("upstairs", rn)] = 100
            for rn in ZONES["downstairs"]["rooms"]:
                room_positions[("downstairs", rn)] = 0
            for rn in ZONES["basement"]["rooms"]:
                room_positions[("basement", rn)] = 0

        elif mode == "Cool Downstairs":
            for rn in ZONES["upstairs"]["rooms"]:
                room_positions[("upstairs", rn)] = 0
            for rn in ZONES["downstairs"]["rooms"]:
                room_positions[("downstairs", rn)] = 100
            for rn in ZONES["basement"]["rooms"]:
                room_positions[("basement", rn)] = 0

        elif mode == "Auto":
            room_positions = self._auto_calculate(
                hvac_mode, hvac_action, eff_cool, eff_heat
            )

        # Concentrate airflow toward any struggling room by throttling already-
        # comfortable rooms. Symmetric: helps hot rooms when cooling, cold rooms
        # when heating. Must run BEFORE backpressure so backpressure remains the
        # final safety net.
        room_positions = self._apply_priority_rooms(
            room_positions, hvac_action, eff_cool, eff_heat, mode
        )

        # Fan-assist redistribution: when the system is idle but a room is still
        # off-target and oppositely-conditioned air is banked elsewhere, run the
        # blower and shove that banked air where it's needed (cold air to a hot
        # room when cooling; warm air to a cold room when heating). Manages the
        # fan mode and may rewrite room_positions. Runs before backpressure.
        room_positions = self._apply_fan_assist(
            room_positions, mode, hvac_action, eff_cool, eff_heat
        )

        # Setpoint nudge (the TRIGGER axis): independently of the vent-position
        # math above, escape the ecobee's whole-house-average blind spot by
        # temporarily moving the setpoint it sees when an OCCUPIED room's
        # measured excess over its margin warrants it. Runs AFTER the priority
        # and fan-assist passes on purpose: it is orthogonal to vent
        # redistribution (which only helps once the compressor runs) and exists
        # purely to make the compressor escalate at all. See the constants block
        # + the method docstring. Guarded to only act in Auto mode and only while
        # the controller is enabled (both enforced by the caller above, but the
        # method re-guards on mode for safety).
        self._apply_setpoint_nudge(hvac_mode, hvac_action, target_cool,
                                   target_heat, mode)

        # Apply backpressure protection (dynamic coil-temp feedback when
        # available, static cap otherwise). Pass hvac_action for the cooling
        # gate and compressor-runtime gate.
        room_positions = self._apply_backpressure_rooms(room_positions, hvac_action)
        # Set vents per room
        for (zone_name, room_name), position in room_positions.items():
            room = ZONES[zone_name]["rooms"][room_name]
            # Per-room max-vent cap (e.g. no-return rooms that can't mix more
            # than half-flow). Clamp here so every code path (Auto, Manual,
            # priority, fan-assist) respects it without per-branch edits.
            max_pct = room.get("max_vent_pct")
            if max_pct is not None and position > max_pct:
                position = max_pct
            for vent in room.get("vents", []):
                self._set_vent(vent, position)

    # ── Auto mode logic ───────────────────────────────────────────────────────

    def _auto_calculate(self, hvac_mode, hvac_action, target_cool, target_heat):
        """Calculate per-ROOM vent positions based on each room's temp,
        occupancy, heat-rise physics, and HVAC state.

        Returns: {(zone_name, room_name): position}

        Key behaviors:
          - Each room is scored independently — rooms near setpoint get
            throttled to 50%, rooms still far from setpoint stay at 100%.
          - Upstairs rooms get a heat-rise bonus when cooling.
          - When HVAC is idle/fan-only: open all for equalization.
          - Hysteresis prevents flapping at setpoint boundaries.
        """

        room_positions = {}  # (zone_name, room_name) -> position

        # If HVAC is idle or fan-only, open everything for equalization.
        if hvac_action in ("idle", "fan", "off", None):
            self.log(f"  HVAC action={hvac_action} — equalizing (all open)")
            for zone_name, zone in ZONES.items():
                for room_name in zone["rooms"]:
                    room_positions[(zone_name, room_name)] = 100
            return room_positions

        # HVAC is actively conditioning. Score each room individually.
        is_cooling = hvac_action == "cooling" or \
            (hvac_mode in ("cool", "heat_cool") and hvac_action != "heating")
        is_heating = hvac_action == "heating" or hvac_mode == "heat"

        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])

                if temp is None:
                    room_positions[key] = 50
                    self.log(f"  {zone_name}/{room_name}: no temp -> 50%")
                    continue

                # Check occupancy
                occ_entity = sensors.get("occupancy")
                is_occupied = True
                if occ_entity:
                    is_occupied = self.get_state(occ_entity) == "on"

                # Occupancy weight: occupied rooms get a bonus to their need
                occ_bonus = 1.0 if is_occupied else 0.0

                if is_cooling:
                    if target_cool is None:
                        room_positions[key] = 50
                        continue
                    need = temp - target_cool
                    # Heat-rise bonus for upstairs
                    if zone_name == "upstairs":
                        need += UPSTAIRS_HEAT_RISE_BONUS
                    elif zone_name == "basement":
                        need -= UPSTAIRS_HEAT_RISE_BONUS
                    # Occupied rooms feel more urgent
                    need += occ_bonus

                elif is_heating:
                    if target_heat is None:
                        room_positions[key] = 50
                        continue
                    need = target_heat - temp
                    if zone_name in ("downstairs", "basement"):
                        need += UPSTAIRS_HEAT_RISE_BONUS
                    need += occ_bonus

                else:
                    room_positions[key] = 100
                    self.log(f"  {zone_name}/{room_name}: unknown action -> 100%")
                    continue

                # Score -> position
                # Unoccupied rooms near/below setpoint should close —
                # no point conditioning an empty room that's comfortable.
                #
                # UNOCCUPIED THROTTLE (per-floor, data-driven): empty rooms
                # start sacrificing airflow (throttle to 50%) at their floor's
                # drift target — downstairs at UNOCC_THROTTLE_DOWNSTAIRS (+2°F),
                # upstairs at UNOCC_THROTTLE_UPSTAIRS (+3°F). The 1st floor has
                # less heat load so we keep it tighter; the 2nd floor's solar
                # load means empty rooms there are allowed to drift further so
                # their cold air feeds the occupied hot rooms (GB1, Game Room).
                # The on_occupancy_change callback fires immediately when
                # someone walks in, so it's back to 100% within 2 seconds.
                #
                # OCCUPANCY OVERRIDE: when a room is >OCCUPANCY_OVERRIDE_OVER
                # above setpoint (absolute floor, default 3°F), give it 100%
                # regardless of occupancy. A hot room needs cooling whether or
                # not someone is in it — ecobee PIR sensors read unoccupied
                # when nobody is moving, and starving a hot room makes the
                # house imbalance worse. Below that floor, per-floor overrides
                # apply to unoccupied rooms only.
                #
                # Heating mirror: same logic — an unoccupied cold room that's
                # still below the heat setpoint gets 50% instead of 100% so its
                # warm air is banked for occupied rooms that need it.
                prev = self._last_zone_positions.get(key)

                # Per-floor unoccupied thresholds (cooling only)
                if is_cooling:
                    if zone_name == "upstairs":
                        unocc_throttle = UNOCC_THROTTLE_UPSTAIRS
                        unocc_hot_override = UNOCC_HOT_OVERRIDE_UP
                        occ_deadband = OCC_DEADBAND_UPSTAIRS
                    else:  # downstairs + basement
                        unocc_throttle = UNOCC_THROTTLE_DOWNSTAIRS
                        unocc_hot_override = UNOCC_HOT_OVERRIDE_DOWN
                        occ_deadband = OCC_DEADBAND_DOWNSTAIRS
                else:  # heating — keep flat thresholds (not the focus of this tuning)
                    unocc_throttle = DEADBAND
                    unocc_hot_override = OCCUPANCY_OVERRIDE_OVER
                    occ_deadband = DEADBAND

                # Zone-presence contention (lever A): a vacant zone's rooms stop
                # grabbing an unconditional 100% via either the absolute
                # OCCUPANCY_OVERRIDE_OVER or the per-floor hot-override while
                # someone elsewhere is off-target. The absolute gate uses the
                # SAME stateful hysteresis helper as the priority/fan-assist
                # passes (single source of truth); the per-floor override uses
                # the stateless elevation (raised, ceiling-capped).
                occ_override = self._effective_occupancy_override(
                    zone_name, key, is_heating) if (occ_entity and not is_occupied) \
                    else OCCUPANCY_OVERRIDE_OVER
                raised_hot_override = self._elevated_threshold(
                    zone_name, unocc_hot_override, is_heating)

                if need > occ_override:
                    pos = 100
                    reason = f"hot override ({need:+.1f}) — 100% regardless of occupancy"
                elif need > raised_hot_override and not is_occupied:
                    # Unoccupied and past the per-floor hot-override (but under
                    # the absolute OCCUPANCY_OVERRIDE_OVER) — give full airflow;
                    # the room is hot enough that cooling it matters even empty.
                    pos = 100
                    reason = f"hot, unoccupied ({need:+.1f}) — 100% (floor override)"
                elif is_occupied:
                    # Per-floor OCCUPIED deadband: downstairs tolerates more
                    # real deviation before locking to 100% (and becoming
                    # donor-immune) than upstairs does — see OCC_DEADBAND_*
                    # comment above. Numerically equal to DEADBAND for
                    # upstairs, so upstairs behavior is unchanged.
                    if need > occ_deadband:
                        pos = 100
                        reason = (f"needs airflow, occupied ({need:+.1f}) "
                                  f"— 100% (floor deadband {occ_deadband:+.1f})")
                    elif need > -DEADBAND:
                        pos = 50
                        reason = f"near setpoint, occupied ({need:+.1f})"
                    else:
                        if prev and prev > 0 and need > -(DEADBAND + HYSTERESIS):
                            pos = 50
                            reason = f"hysteresis ({need:+.1f})"
                        else:
                            pos = 0
                            reason = f"satisfied ({need:+.1f})"
                elif need > DEADBAND * 3:
                    pos = 50
                    reason = f"high need, unoccupied ({need:+.1f}) — 50%"
                elif need > DEADBAND:
                    # Per-floor unoccupied throttle: sacrifice empty rooms
                    # at their floor's drift target.
                    if need > unocc_throttle:
                        pos = 50
                        reason = (f"needs airflow, unoccupied ({need:+.1f}) "
                                  f"— 50% (floor throttle {unocc_throttle:+.0f})")
                    else:
                        pos = 50
                        reason = f"needs airflow, unoccupied ({need:+.1f}) — 50%"
                elif need > -DEADBAND:
                    # Unoccupied and near setpoint — close it
                    if prev and prev > 0 and need > -(DEADBAND + HYSTERESIS):
                        pos = 50
                        reason = f"unoccupied hysteresis ({need:+.1f})"
                    else:
                        pos = 0
                        reason = f"unoccupied, near setpoint ({need:+.1f})"
                else:
                    if prev and prev > 0 and need > -(DEADBAND + HYSTERESIS):
                        pos = 50
                        reason = f"hysteresis ({need:+.1f})"
                    else:
                        pos = 0
                        reason = f"satisfied ({need:+.1f})"

                room_positions[key] = pos
                self._last_zone_positions[key] = pos

                occ_str = "occ" if is_occupied else "empty"
                self.log(f"  {zone_name}/{room_name}: {temp:.1f}F "
                         f"{occ_str} need={need:+.1f} -> {pos}% ({reason})")

        return room_positions

    # ── Priority-room airflow concentration ───────────────────────────────────

    @staticmethod
    def _duct_sensor_for_vent(vent_entity):
        """Map a Flair cover entity to its duct (supply-air) temp sensor.

        cover.guest_bedroom_1_8d6d_vent     -> sensor.guest_bedroom_1_8d6d_duct_temperature
        cover.dining_room_7a28_vent_2       -> sensor.dining_room_7a28_duct_temperature_2
        """
        s = vent_entity.replace("cover.", "sensor.", 1)
        return re.sub(r"_vent(_\d+)?$",
                      lambda m: "_duct_temperature" + (m.group(1) or ""), s)

    def _update_supply_penalties(self, heating=False):
        """Measure each room's supply-air penalty from the duct sensors and fold
        it into the smoothed EMA. Only meaningful when air is actually moving;
        otherwise duct temps drift to ambient and mean nothing.

        The handicap INVERTS by mode (validated against May 7 heating data:
        Main Bathroom had the WARMEST duct while cooling but the COLDEST duct
        while heating — it's the worst-served room either way):
          - cooling: best supply is the COLDEST duct; penalty = duct - house_min
          - heating: best supply is the HOTTEST duct; penalty = house_max - duct
        A large penalty == this room gets the least-effective supply air for the
        current mode, so it should react earlier.
        """
        room_duct = {}
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                vals = []
                for v in sensors.get("vents", []):
                    # A throttled/closed vent reads a stale duct simply because
                    # air isn't flowing past the sensor — that's not a delivery
                    # handicap. Only sample ducts whose vent is open enough for
                    # the reading to reflect real supply-air temperature.
                    tilt = self.get_state(v, attribute="current_tilt_position")
                    try:
                        if tilt is not None and int(tilt) < DUCT_SAMPLE_MIN_TILT:
                            continue
                    except (TypeError, ValueError):
                        pass
                    dt = self._read_temp(self._duct_sensor_for_vent(v))
                    if dt is not None:
                        vals.append(dt)
                if vals:
                    # A room's effective supply is its most-useful duct for the
                    # mode: hottest when heating, coldest when cooling.
                    room_duct[(zone_name, room_name)] = (
                        max(vals) if heating else min(vals))

        if len(room_duct) < 2:
            return  # not enough data to compare

        if heating:
            house_best = max(room_duct.values())   # hottest supply available
        else:
            house_best = min(room_duct.values())   # coldest supply available

        for key, duct in room_duct.items():
            penalty = (house_best - duct) if heating else (duct - house_best)
            penalty = max(0.0, penalty)
            if penalty < PRIORITY_PENALTY_MIN_SAMPLE:
                penalty = 0.0
            prev = self._supply_penalty.get(key)
            if prev is None:
                self._supply_penalty[key] = penalty
            else:
                self._supply_penalty[key] = (
                    PRIORITY_PENALTY_EMA * penalty
                    + (1 - PRIORITY_PENALTY_EMA) * prev
                )

    def _update_delivery_penalties(self, hvac_action, target_cool, target_heat):
        """Measure each room's achieved-conditioning-rate handicap and fold it
        into a smoothed EMA. This is the capacity/load axis that supply-air
        temperature cannot see.

        SYMMETRIC across cooling and heating (winter must work too):
          - cooling: beneficiary is ABOVE cool setpoint; off = temp - setpoint;
            approach toward setpoint = temp FALLING (prev_temp - temp).
          - heating: beneficiary is BELOW heat setpoint; off = setpoint - temp;
            approach toward setpoint = temp RISING (temp - prev_temp).
        A capacity-limited room (one undersized vent, heavy load) lags the same
        way in both seasons, so the handicap is measured identically; only the
        sign of "off" and "approach" flips. Covered by the heating-mirror tests
        (T9-T13) in test_delivery_penalty.py.

        For each room we compute the rate of approach to the active setpoint
        since the last cycle (°F/min, positive = getting closer). A room accrues
        a delivery penalty only when ALL of these hold, so we isolate a genuine
        delivery/capacity handicap and never double-count the supply-air axis:
          - HVAC is actively conditioning in this mode,
          - the room is occupied (we only care about rooms that matter, and
            occupancy load is part of the handicap),
          - the room is past the deadband in the wrong direction (needs help),
          - the room's vents are effectively wide open (we're already giving it
            all the airflow we can — so a slow rate isn't just a throttled vent),
          - its supply penalty is low (good supply air — otherwise the supply
            mechanism already owns this room and we'd be double-counting),
          - yet its approach rate is below DELIVERY_STUCK_RATE (it's stuck).
        The per-sample contribution is the °F still-off, capped, so a room that
        is both very off-target AND stuck accrues fastest. When any precondition
        fails (esp. once the room finally starts moving), we feed 0 into the EMA
        so the penalty decays — self-correcting, no manual reset.
        """
        if hvac_action == "cooling" and target_cool is not None:
            heating = False
            setpoint = target_cool
        elif hvac_action == "heating" and target_heat is not None:
            heating = True
            setpoint = target_heat
        else:
            # Not conditioning — don't measure (rate is meaningless), and let
            # any existing penalty decay so it doesn't persist across an idle gap.
            now = self.datetime(aware=True)
            for key in list(self._delivery_penalty):
                self._delivery_penalty[key] *= (1 - DELIVERY_PENALTY_EMA)
            self._delivery_last = {}
            return

        now = self.datetime(aware=True)

        def off_by(t):
            return (setpoint - t) if heating else (t - setpoint)

        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue

                prev = self._delivery_last.get(key)
                self._delivery_last[key] = (temp, now)

                contribution = 0.0
                stuck = False
                if prev is not None:
                    prev_temp, prev_time = prev
                    dt_min = (now - prev_time).total_seconds() / 60.0
                    if DELIVERY_MIN_DT_MIN <= dt_min <= DELIVERY_MAX_DT_MIN:
                        off = off_by(temp)
                        occ_entity = sensors.get("occupancy")
                        occupied = (occ_entity is None
                                    or self.get_state(occ_entity) == "on")
                        # Effectively wide open? Every vent at/above the duct-
                        # sample threshold means we're already giving it all the
                        # airflow we can.
                        wide_open = True
                        for v in sensors.get("vents", []):
                            tilt = self.get_state(
                                v, attribute="current_tilt_position")
                            try:
                                if tilt is not None and int(tilt) < DUCT_SAMPLE_MIN_TILT:
                                    wide_open = False
                                    break
                            except (TypeError, ValueError):
                                pass
                        well_supplied = (
                            self._supply_penalty.get(key, 0.0)
                            < PRIORITY_PENALTY_MIN_SAMPLE)
                        # rate toward setpoint: cooling -> temp should fall, so
                        # approach = prev_temp - temp; heating -> temp - prev_temp.
                        approach = ((prev_temp - temp) if not heating
                                    else (temp - prev_temp))
                        rate = approach / dt_min
                        if (occupied and off > DEADBAND and wide_open
                                and well_supplied and rate < DELIVERY_STUCK_RATE):
                            stuck = True
                            contribution = min(off, DELIVERY_PENALTY_MAX)

                prevp = self._delivery_penalty.get(key, 0.0)
                self._delivery_penalty[key] = (
                    DELIVERY_PENALTY_EMA * contribution
                    + (1 - DELIVERY_PENALTY_EMA) * prevp
                )
                if stuck:
                    self.log(
                        f"Delivery handicap: {room_name} stuck "
                        f"(off={off_by(temp):+.1f}F, well-supplied, wide open, "
                        f"rate<{DELIVERY_STUCK_RATE}F/min) -> penalty "
                        f"{self._delivery_penalty[key]:.2f}")

        self._publish_delivery_penalty()

    def _publish_delivery_penalty(self):
        """Expose the delivery-handicap signal as ONE summary sensor.

        State = current max delivery penalty across all rooms (a numeric "is any
        room capacity-stuck right now" gauge that the Prometheus export ships to
        VictoriaMetrics). Per-room values ride along as attributes for the HA UI.
        One entity instead of 13 keeps the prod entity surface small while still
        making the new axis observable. Best-effort — never breaks control.
        """
        try:
            per_room = {f"{rn}": round(p, 2)
                        for (zn, rn), p in self._delivery_penalty.items()
                        if p >= 0.01}
            worst = max(self._delivery_penalty.values(), default=0.0)
            # state must be a string, not a bare 0.0/0. AppDaemon's HTTP
            # kwarg-cleaning (utils.clean_http_kwargs -> remove_literals)
            # strips any kwarg whose value is `in (None, False)` — and in
            # Python 0.0 == False, so a literal 0.0 state gets silently
            # dropped from the outgoing POST body entirely. HA's REST API
            # then 400s with "No state specified." Reproduced directly
            # against /api/states on 2026-07-17: identical payload with
            # state=0.0 (float) fails, state="0.0" (str) succeeds. Only
            # bites when the house is fully caught up (worst == 0.0), which
            # is exactly why it was intermittent instead of constant.
            self.set_state(
                DELIVERY_PENALTY_ENTITY,
                state=str(round(worst, 2)),
                attributes={
                    # Deliberately NO temperature unit / device_class: HA's
                    # Prometheus export would otherwise classify this as a
                    # temperature, rename it to *_temperature_celsius AND convert
                    # the value F->C. We want a plain numeric gauge exported as
                    # homeassistant_sensor_state. The value is in °F of overshoot;
                    # the friendly name carries that for humans.
                    "friendly_name": "Smart Vent Delivery Handicap max F",
                    "icon": "mdi:fan-alert",
                    "stuck_rooms": per_room,
                },
            )
        except Exception as e:
            self.log(f"delivery-penalty publish failed (non-fatal): {e}")

    def _weather_factor(self, heating=False):
        """Amplify supply penalties when outdoor temp makes the handicap bite.

        Cooling: hotter outside -> handicap matters more (ramps above HOT_BASE_F).
        Heating: colder outside -> handicap matters more (ramps below COLD_BASE_F).
        Returns 1.0 in the mild band or if the weather entity is unavailable.
        """
        outdoor = None
        w = self.get_state(WEATHER_ENTITY, attribute="temperature")
        if w is not None:
            try:
                outdoor = float(w)
            except (TypeError, ValueError):
                outdoor = None
        if outdoor is None:
            return 1.0
        if heating:
            if outdoor >= COLD_BASE_F:
                return 1.0
            factor = 1.0 + (COLD_BASE_F - outdoor) / COLD_SPAN_F
            return min(factor, HOT_FACTOR_MAX)
        if outdoor <= HOT_BASE_F:
            return 1.0
        factor = 1.0 + (outdoor - HOT_BASE_F) / HOT_SPAN_F
        return min(factor, HOT_FACTOR_MAX)

    def _room_margin(self, key, heating=False, base_margin=None):
        """Activation margin (°F past the active setpoint) for a room.

        Derived from the room's measured supply-air penalty (which is already
        mode-correct from _update_supply_penalties), amplified by how extreme it
        is outside. A handicapped room gets a lower (earlier-engaging) margin
        automatically, in BOTH heating and cooling. Override, if present, wins.

        base_margin lets a caller use a DIFFERENT ceiling than the priority
        pass's PRIORITY_MARGIN_BASE while still getting the same handicap-
        driven pull-down — e.g. fan-assist calls this with
        base_margin=FAN_ASSIST_OVER so an unhandicapped room keeps its
        original (higher, more conservative) activation gap, while a room
        with a measured supply or delivery handicap still engages earlier,
        proportionally, off that same base.
        """
        if key in PRIORITY_MARGIN_OVERRIDES:
            return PRIORITY_MARGIN_OVERRIDES[key]
        if base_margin is None:
            base_margin = PRIORITY_MARGIN_BASE
        penalty = self._supply_penalty.get(key, 0.0)
        # Two orthogonal handicap axes both pull the margin down (engage earlier):
        #   - supply penalty: warm/ineffective supply air (GB1), weather-amplified.
        #   - delivery penalty: well-supplied but stuck — capacity/load (GB2).
        # They are measured under mutually-exclusive conditions (delivery only
        # accrues when supply penalty is low), so summing them never
        # double-counts the same room on the same cause.
        delivery = self._delivery_penalty.get(key, 0.0)
        margin = (base_margin
                  - PRIORITY_PENALTY_GAIN * penalty * self._weather_factor(heating)
                  - DELIVERY_MARGIN_GAIN * delivery)
        return max(PRIORITY_MARGIN_MIN, min(base_margin, margin))

    # ── Zone-presence contention (measured axis) ───────────────────────────────
    # These helpers make the beneficiary/self-protect threshold RELATIVE and the
    # donor threshold RELAXED for rooms in zones that are currently vacant while
    # someone elsewhere is off-target. They are the measured-axis counterparts to
    # _update_supply_penalties / _update_delivery_penalties / _room_margin: all
    # four are recomputed fresh every cycle from real sensors and decay back to
    # neutral (contention == 0.0 == today's behavior) when the trigger clears.
    # Both _apply_priority_rooms and _apply_fan_assist call the SAME two shared
    # helpers (_effective_occupancy_override / _donor_cooler_by), so the two
    # gated passes can't drift out of sync — the recurring bug class in this file.

    def _ensure_zone_presence_state(self):
        """Lazily (re)initialize the zone-presence state attributes if missing.

        Defensive lazy-init so the helpers work even when the app was created
        without initialize() running (the offline test fakes subclass the
        controller directly, and must keep working unmodified). No-op once the
        attrs exist.
        """
        if not hasattr(self, "_zone_last_occupied"):
            self._zone_last_occupied = {}
        if not hasattr(self, "_zone_occupied"):
            self._zone_occupied = {}
        if not hasattr(self, "_zone_vacancy_demoted"):
            self._zone_vacancy_demoted = set()

    def _update_zone_presence(self):
        """Refresh each zone's presence state from its rooms' occupancy sensors.

        Public helpers all rely on the per-zone vacancy booleans that this
        stamps for the current cycle into self._zone_occupied[zone]:
          - For each zone, if ANY of its rooms currently reads occupancy "on",
            stamp self._zone_last_occupied[zone] = now (and _zone_occupied=True).
          - A zone whose rooms are all "off" keeps its prior last_occupied stamp
            (it stays "occupied" for the debounce window — see _zone_is_vacant).
          - Rooms with a missing/unavailable occupancy entity are ignored
            (never treated as occupied).
        Also publishes the observability sensor and logs the per-zone picture.

        The state attrs are lazily initialized so the helpers are safe to call
        even when the app was instantiated outside initialize() (e.g. the
        offline test fakes, which subclass without running it).
        """
        self._ensure_zone_presence_state()
        now = self.datetime()
        for zone_name, zone in ZONES.items():
            occupied = False
            for room_name, sensors in zone["rooms"].items():
                occ = sensors.get("occupancy")
                if not occ:
                    continue
                state = self.get_state(occ)
                if state == "on":
                    occupied = True
                    break
            if occupied:
                self._zone_last_occupied[zone_name] = now
            self._zone_occupied[zone_name] = occupied
        self._publish_zone_presence()
        # Log the per-zone picture (and contention for vacant zones) so the
        # live AppDaemon log makes the measured axis visible. Greppable line the
        # deploy dispatch verifies the fix on the live house with.
        try:
            _hmode, _hact, tc, th = self._get_thermostat_state()
            # Pick heating direction iff the active action is heating.
            _heating = (_hact == "heating")
            parts = []
            for zn2 in ZONES:
                last2 = self._zone_last_occupied.get(zn2)
                if last2 is None:
                    age_s = ">24h"
                else:
                    mins2 = (now - last2).total_seconds() / 60.0
                    age_s = ">24h" if mins2 > 24 * 60 else f"{round(mins2, 1):.1f}m"
                parts.append(f"{zn2} {'OCCUPIED' if not self._zone_is_vacant(zn2) else 'VACANT'} ({age_s} ago)")
            cents = []
            for zn2 in ZONES:
                if self._zone_is_vacant(zn2):
                    cents.append(f"contention({zn2})={self._zone_contention(zn2, _heating):.2f}")
            self.log("zone presence: " + ", ".join(parts)
                     + (" | " + ", ".join(cents) if cents else ""))
        except Exception as e:
            self.log(f"zone-presence log failed (non-fatal): {e}")

    def _zone_is_vacant(self, zone):
        """True iff `zone` counts as vacant for this cycle.

        Vacant means no room in the zone has read occupancy "on" within the last
        ZONE_PRESENCE_HOLD_MIN minutes. A zone never seen occupied since app
        start counts as vacant.
        """
        self._ensure_zone_presence_state()
        last = self._zone_last_occupied.get(zone)
        if last is None:
            return True
        age = (self.datetime() - last).total_seconds() / 60.0
        return age > ZONE_PRESENCE_HOLD_MIN

    def _zone_contention(self, zone, heating):
        """How badly some OTHER zone's occupants need air right now, in [0, 1].

        Scans every zone z != `zone` that is NOT vacant. For each such zone,
        zone_demand[z] = the maximum "excess" over any of its (occupancy-
        eligible) rooms' measured _room_margin, else 0.0, where
            excess = off_target(room) - _room_margin(room, heating),
            clamped at >= 0.
        off_target is sign-aware: (room_temp - cool_setpoint) when cooling,
        (heat_setpoint - room_temp) when heating.

        contention = clamp(max(zone_demand.values()) / ZONE_CONTENTION_SPAN_F, 0, 1).
        If no other zone is occupied, or no occupied room is past its margin,
        this returns EXACTLY 0.0 (both levers then collapse to identity).
        """
        if len(ZONES) < 2:
            return 0.0
        zone_demand = {}
        for zname, z in ZONES.items():
            if zname == zone:
                continue
            if self._zone_is_vacant(zname):
                continue
            demand = 0.0
            for room_name, sensors in z["rooms"].items():
                occ_entity = sensors.get("occupancy")
                if occ_entity and self.get_state(occ_entity) != "on":
                    # A room whose PIR currently reads "off" isn't an occupant
                    # needing air right now — skip it (the zone's actual
                    # occupant still registers via their own "on" room). A room
                    # with no occupancy sensor is treated as eligible, matching
                    # the rest of the file (no sensor => assumed occupied).
                    continue
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                off = self._off_target(room_name, temp, heating)
                margin = self._room_margin((zname, room_name), heating)
                excess = off - margin
                if excess > 0:
                    demand = max(demand, excess)
            zone_demand[zname] = demand
        if not zone_demand:
            return 0.0
        worst = max(zone_demand.values())
        if worst <= 0.0:
            return 0.0
        return max(0.0, min(1.0, worst / ZONE_CONTENTION_SPAN_F))

    def _off_target(self, room_name, temp, heating):
        """Sign-aware off-target magnitude for a room in the current mode.

        Cooling (heating=False): (room_temp - cool_setpoint), i.e. how hot.
        Heating (heating=True):  (heat_setpoint - room_temp), i.e. how cold.
        Both are positive when the room needs help.
        """
        setpoint = self._current_setpoint(heating)
        if setpoint is None:
            return 0.0
        return (setpoint - temp) if heating else (temp - setpoint)

    def _current_setpoint(self, heating):
        """Return the active setpoint (cool or heat) from the thermostat state."""
        _mode, _action, target_cool, target_heat = self._get_thermostat_state()
        if heating:
            return target_heat
        return target_cool

    def _elevated_threshold(self, zone, base, heating):
        """Contention-adjusted ceiling for a VACANT zone, without hysteresis.

        Stateless (no demotion-set side effects) — used by _auto_calculate to
        raise a per-floor hot-override / self-protect threshold in a vacant zone:

            raised = base + ZONE_VACANCY_OVERRIDE_BONUS_F * contention
            raised = min(raised, ZONE_VACANCY_OVERRIDE_CEILING_F)   # bake protection

        When the zone is occupied (or contention 0) this returns `base`
        unchanged (identity). The ceiling cap guarantees a genuinely baking room
        is never starved even at full contention.
        """
        if not self._zone_is_vacant(zone):
            return base
        c = self._zone_contention(zone, heating)
        if c <= 0.0:
            return base
        raised = base + ZONE_VACANCY_OVERRIDE_BONUS_F * c
        return min(raised, ZONE_VACANCY_OVERRIDE_CEILING_F)

    def _effective_occupancy_override(self, zone, key, heating):
        """Contention-adjusted replacement for the bare OCCUPANCY_OVERRIDE_OVER.

        The single chokepoint for lever A, called by BOTH the priority pass and
        the fan-assist pass (recurring-bug-class guard), so the demotion state
        and hysteresis behavior can never drift out of sync.

        If `zone` is NOT vacant -> return OCCUPANCY_OVERRIDE_OVER unchanged (and
        clear the room's demotion entry so a returning occupant isn't held back).
        Else:
            raised = OCCUPANCY_OVERRIDE_OVER + ZONE_VACANCY_OVERRIDE_BONUS_F * c
            raised = min(raised, ZONE_VACANCY_OVERRIDE_CEILING_F)
        Then apply per-room hysteresis around `raised` using the current demotion
        state (self._zone_vacancy_demoted, a set of (zone, room) keys):
          - PROTECTED (not demoted): beneficiary while off >= raised; once off
            falls BELOW raised the room is demoted (suppressed to a donor).
          - DEMOTED (held as a donor): stays a donor while off < raised + HYST;
            once off EXCEEDS raised + HYST it re-promotes to protected.
        The returned value is the effective threshold the caller compares `off`
        against: a room whose off is below it is NOT a beneficiary (it stays
        eligible as a donor); at/above it the room re-locks into 100%.
        """
        # _off_target needs the room's temp; derive it here.
        room_temp = self._read_temp(ZONES[key[0]]["rooms"][key[1]]["temp"])
        if not self._zone_is_vacant(zone):
            # Zone occupied — identity. Clear any stale demotion entry so a
            # returning occupant isn't held back by hysteresis.
            self._zone_vacancy_demoted.discard(key)
            return OCCUPANCY_OVERRIDE_OVER

        c = self._zone_contention(zone, heating)
        raised = OCCUPANCY_OVERRIDE_OVER + ZONE_VACANCY_OVERRIDE_BONUS_F * c
        raised = min(raised, ZONE_VACANCY_OVERRIDE_CEILING_F)

        off = self._off_target(key[1], room_temp, heating)
        if key in self._zone_vacancy_demoted:
            # Demoted: held as a donor. Re-promote (return raised, so off >=
            # raised makes it a beneficiary again) only once off EXCEEDS
            # raised + HYST — the required hysteresis band.
            if off >= raised + ZONE_VACANCY_OVERRIDE_HYST_F:
                self._zone_vacancy_demoted.discard(key)
                return raised
            return raised + ZONE_VACANCY_OVERRIDE_HYST_F
        else:
            # Protected: a beneficiary while off >= raised. Demote (suppress to
            # a donor) once it falls below raised.
            if off < raised:
                self._zone_vacancy_demoted.add(key)
                return raised + ZONE_VACANCY_OVERRIDE_HYST_F
            return raised

    def _forget_demoted_rooms(self):
        """Clear demotion state for any room whose zone is no longer vacant.

        Keeps the hysteresis set from growing stale: once a zone reads occupied
        again, its rooms are immediately eligible for the standard (identity)
        threshold on the next cycle.
        """
        stale = {key for key in self._zone_vacancy_demoted
                 if not self._zone_is_vacant(key[0])}
        if stale:
            self._zone_vacancy_demoted.difference_update(stale)

    def _donor_cooler_by(self, donor_zone, base_cooler_by, heating):
        """Relaxed "must be cooler by" requirement for a DONOR candidate's zone.

        When the candidate donor's OWN zone is VACANT, its protected self-interest
        is weaker, so we waive ZONE_VACANCY_DONOR_RELAX * contention of the
        requirement:
            required = base_cooler_by * (1.0 - ZONE_VACANCY_DONOR_RELAX * c)
            required = max(required, ZONE_VACANCY_DONOR_MIN_COOLER_F)
        The max(...) floor is the hard thermodynamic guard: we never pull air
        from a room that isn't at least ZONE_VACANCY_DONOR_MIN_COOLER_F more
        comfortable than the beneficiary (cooler when cooling, warmer when
        heating). When the donor's zone is occupied (or contention is 0), this
        returns base_cooler_by unchanged. `heating` is passed for the contention
        computation only.
        """
        # The contention-based relaxation is reserved for a VACANT donor zone: an
        # OCCUPIED zone's rooms still deserve their full protected "must be cooler
        # by" requirement even when someone elsewhere is suffering (contention
        # scans OTHER zones, so an occupied zone can easily see non-zero
        # contention for itself). Matches the docstring and both call-site
        # comments — see _apply_priority_rooms / _apply_fan_assist.
        if not self._zone_is_vacant(donor_zone):
            return base_cooler_by
        c = self._zone_contention(donor_zone, heating)
        if c <= 0.0:
            return base_cooler_by
        required = base_cooler_by * (1.0 - ZONE_VACANCY_DONOR_RELAX * c)
        return max(required, ZONE_VACANCY_DONOR_MIN_COOLER_F)

    def _publish_zone_presence(self):
        """Expose the zone-presence axis as one summary sensor (best-effort).

        State is a short human/alert summary string. Attributes carry each
        zone's occupied/vacant bool, its last-occupied age in minutes, and the
        computed contention (as a float attribute — HA attributes accept floats
        fine; only a bare float STATE would hit the silent-write drop, so we
        always keep the state itself a string, per the delivery-penalty fix).
        """
        try:
            now = self.datetime()
            zone_attrs = {}
            for zname in ZONES:
                last = self._zone_last_occupied.get(zname)
                if last is None:
                    age_display = ">24h"
                else:
                    mins = (now - last).total_seconds() / 60.0
                    if mins > 24 * 60:
                        age_display = ">24h"
                    else:
                        age_display = round(mins, 1)
                vacant = self._zone_is_vacant(zname)
                zone_attrs[f"{zname}"] = (
                    "VACANT" if vacant else "OCCUPIED",
                    age_display,
                )
            # Pick a representative contention (used for the state + logs): the
            # largest contention across all zones is the most informative gauge.
            # We log per-zone so the deploy dispatch can grep; the sensor is one
            # entity to keep the prod entity surface small (matches DELIVERY
            # _PENALTY_ENTITY pattern).
            worst_c = 0.0
            for zname in ZONES:
                c = self._zone_contention(zname, False)
                worst_c = max(worst_c, c)
            self.set_state(
                ZONE_PRESENCE_ENTITY,
                state="occupied-contention" if worst_c > 0 else "no-contention",
                attributes={
                    "friendly_name": "Smart Vent Zone Presence/Contention",
                    "icon": "mdi:home-account",
                    "zones": {z: {"vacant": v, "last_occupied_min": a}
                              for z, (v, a) in zone_attrs.items()},
                    "max_contention": round(worst_c, 3),
                },
            )
        except Exception as e:
            self.log(f"zone-presence publish failed (non-fatal): {e}")

    def _apply_priority_rooms(self, room_positions, hvac_action,
                              target_cool, target_heat=None, mode=None):
        """Redirect CFM toward ANY struggling room by throttling rooms that are
        already comfortable. Symmetric across heating and cooling.

        Generalized over the whole house: every occupied room is eligible to be
        a beneficiary when it's the one falling behind the active setpoint. When
        several rooms are off-target they all sit at 100% and none gets a larger
        *share* of supply air — the only lever that moves more CFM to a needy
        room is throttling OTHER, satisfied rooms. Worst-room-first.

        Cooling: beneficiary = above cool setpoint; donor = cooler than it.
        Heating: beneficiary = below heat setpoint; donor = warmer than it.

        A beneficiary is never also a donor. If the whole house is uniformly off
        there are no eligible donors and this is a no-op. Mutates and returns
        room_positions.

        SKIPPED in Cool Upstairs / Cool Downstairs modes — those are explicit
        whole-house redirections and the priority pass would re-pin hot rooms
        in the closed zone back to 100% as beneficiaries, defeating the mode.
        """
        if mode in ("Cool Upstairs", "Cool Downstairs"):
            return room_positions
        if hvac_action == "cooling" and target_cool is not None:
            heating = False
            setpoint = target_cool
        elif hvac_action == "heating" and target_heat is not None:
            heating = True
            setpoint = target_heat
        else:
            return room_positions

        # "off" = how far past the setpoint in the unhelpful direction (always
        # positive when the room needs help). Cooling: temp - setpoint (too hot).
        # Heating: setpoint - temp (too cold).
        def off_by(t):
            return (setpoint - t) if heating else (t - setpoint)

        precool = self.datetime().hour in PRECOOL_HOURS

        # Build the beneficiary list: every occupied room past its (possibly
        # pre-conditioning-lowered) activation margin. Worst-first.
        beneficiaries = []  # (off, key, temp, escalated, is_occupied)
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                occ_entity = sensors.get("occupancy")
                is_occupied = (not occ_entity) or self.get_state(occ_entity) == "on"
                off = off_by(temp)
                # Occupancy gate: only help occupied rooms, UNLESS the room is
                # significantly over setpoint (OCCUPANCY_OVERRIDE_OVER). ecobee
                # PIR sensors read unoccupied when nobody is moving, even if
                # the room is hot — don't starve a hot room of airflow just
                # because it's empty.
                #
                # Zone-presence contention: this threshold is now RELATIVE for
                # rooms in a VACANT zone — an empty room in a zone whose
                # occupants are nowhere near must be considerably hotter before
                # it can lock itself into protected-beneficiary status (and out
                # of donor eligibility) while another floor's occupants are
                # suffering. _occ_override is the single shared decision both
                # this pass and fan-assist use (recurring-bug-class guard).
                _occ_override = self._effective_occupancy_override(
                    zone_name, key, heating)
                if occ_entity and not is_occupied:
                    if off < _occ_override:
                        continue  # unoccupied and not hot enough to override
                    # Hot enough to override the PIR false-negative. Treat as
                    # occupied for sort purposes too — a room this hot is a
                    # priority regardless of what the motion sensor says, and
                    # the occupied-first sort would otherwise put it behind
                    # less-hot but occupied rooms (e.g. GB1 at +8F empty
                    # losing donors to Living Room at +5F occupied).
                    is_occupied = True
                # donor_only rooms never become beneficiaries — they can be
                # throttled as donors but never steal airflow for themselves.
                if sensors.get("donor_only"):
                    continue
                margin = self._room_margin(key, heating)
                eff_margin = (PRECOOL_MARGIN
                              if (precool and PRECOOL_MARGIN < margin)
                              else margin)
                off = off_by(temp)
                if off <= eff_margin:
                    continue
                # Escalate (throttle donors to 0% not 50%) when the room is far
                # over setpoint, OR when it carries a real delivery handicap: a
                # capacity-limited room (GB2) is already wide open, so maximum
                # donor throttling is the only software lever left to push more
                # CFM at it — don't wait for it to drift 4°F over first.
                escalated = (off >= PRIORITY_ESCALATE_OVERRIDES.get(key, PRIORITY_ESCALATE_OVER)
                             or self._delivery_penalty.get(key, 0.0)
                             >= DELIVERY_ESCALATE_PENALTY)
                beneficiaries.append((off, key, temp, escalated, is_occupied))

        if not beneficiaries:
            return room_positions

        # Sort: OCCUPIED beneficiaries first, then largest deviation first.
        # An occupied room that's struggling wins donor airflow over an empty
        # room with a larger deviation — the empty room still gets its own
        # vents at 100% (OCCUPANCY_OVERRIDE), but it shouldn't steal donor
        # CFM from an occupied room that also needs help.
        beneficiaries.sort(key=lambda b: (b[4], b[0]), reverse=True)
        beneficiary_keys = {b[1] for b in beneficiaries}

        for off, key, temp, escalated, _is_occupied in beneficiaries:
            zone_name, room_name = key
            donor_pos = (PRIORITY_DONOR_POS_ESCALATED if escalated
                         else PRIORITY_DONOR_POS)

            # Pin the beneficiary fully open.
            room_positions[key] = 100

            # Donors: rooms at least PRIORITY_DONOR_COOLER_BY °F more comfortable
            # (cooling: cooler; heating: warmer) than this beneficiary, that are
            # NOT themselves beneficiaries, and aren't already throttled.
            donors = []
            for (zn, rn), pos in room_positions.items():
                if (zn, rn) == key or (zn, rn) in beneficiary_keys:
                    continue
                droom = ZONES[zn]["rooms"][rn]
                dtemp = self._read_temp(droom["temp"])
                if dtemp is None:
                    continue
                # Donor must have real margin in the helpful direction.
                # Cross-floor relaxation (cooling only): a downstairs donor
                # feeding an upstairs beneficiary needs less proven gap than
                # the flat PRIORITY_DONOR_COOLER_BY — downstairs runs cooler
                # on average (96h data, 2026-07-17), so we trust it sooner.
                cooler_by = PRIORITY_DONOR_COOLER_BY
                if (not heating and zone_name == "upstairs"
                        and zn == "downstairs"):
                    cooler_by = PRIORITY_DONOR_COOLER_BY_CROSS_FLOOR
                # Zone-presence contention (lever B): when this donor's OWN zone
                # is vacant, its protected self-interest is weaker, so we waive
                # up to ZONE_VACANCY_DONOR_RELAX * contention of the
                # "must be cooler by" requirement (composed multiplicatively on
                # top of whichever base applies) — but never below the
                # ZONE_VACANCY_DONOR_MIN_COOLER_F thermodynamic floor.
                cooler_by = self._donor_cooler_by(zn, cooler_by, heating)
                if heating:
                    if dtemp < temp + cooler_by:
                        continue  # not enough warmer than the cold beneficiary
                else:
                    if dtemp > temp - cooler_by:
                        continue  # not enough cooler than the hot beneficiary
                if pos <= donor_pos:
                    continue  # already at/below the chosen throttle position
                docc = droom.get("occupancy")
                doccupied = self.get_state(docc) == "on" if docc else False
                donors.append(((zn, rn), doccupied, dtemp))

            # Unoccupied first; then the most-comfortable donor gives up air most
            # safely (coolest when cooling, warmest when heating).
            donors.sort(key=lambda x: (x[1], -x[2] if heating else x[2]))
            throttled = 0
            for dkey, docc, dtemp in donors:
                if throttled >= PRIORITY_MAX_DONORS:
                    break
                room_positions[dkey] = donor_pos
                throttled += 1
                # Include zone-presence context so the live log makes the
                # measured axis visible: contention for the donor's (vacant)
                # zone and whether its room was demoted (eligible as a donor
                # that otherwise wouldn't have been).
                dz = dkey[0]
                d_vacant = self._zone_is_vacant(dz)
                d_c = self._zone_contention(dz, heating)
                zctx = ""
                if d_vacant and d_c > 0.0:
                    zctx = (f" (zone vacant, contention {d_c:.2f}"
                            + (", demoted" if dkey in self._zone_vacancy_demoted else "")
                            + ")")
                self.log(f"  Priority {room_name} ({temp:.1f}F): throttling "
                         f"{dz}/{dkey[1]} ({dtemp:.1f}F, "
                         f"{'occ' if docc else 'empty'}) -> {donor_pos}%{zctx}")

            mode_tag = "heat" if heating else "cool"
            tag = [mode_tag]
            if escalated:
                tag.append("ESCALATED")
            if precool and self._room_margin(key, heating) > PRECOOL_MARGIN:
                tag.append("pre" + mode_tag)
            tagstr = f" [{','.join(tag)}]"

            if throttled == 0:
                self.log(f"  Priority {room_name} ({temp:.1f}F, off{off:+.1f})"
                         f"{tagstr} struggling but no donor rooms")
            else:
                self.log(f"  Priority {room_name} ({temp:.1f}F, off{off:+.1f})"
                         f"{tagstr}: pinned 100%, redirected flow from "
                         f"{throttled} room(s) -> {donor_pos}%")

        return room_positions

    # ── Fan-assist redistribution ─────────────────────────────────────────────

    def _apply_fan_assist(self, room_positions, mode, hvac_action,
                          target_cool, target_heat=None):
        """Force-circulate banked conditioned air to ANY off-target room when the
        system is idle. Symmetric across heating and cooling.

        The single hallway thermostat goes idle on house AVERAGE, leaving an
        individual room off-target while oppositely-conditioned air sits banked
        elsewhere (cold air in the basement after AC; warm air in a sunny room
        after heat). This runs the air handler fan (no compressor, no conditioning
        cost), opens the needy room(s), and chokes the banked rooms so their air
        is pushed where it's needed. Releases the fan to auto when no longer
        needed. House-wide, worst-room-first.

        Cooling season: push banked COLD air to a hot room.
        Heating season: push banked WARM air to a cold room.

        Decides direction from the thermostat's recent action / mode. Only acts
        in Auto. Mutates and returns room_positions; sets fan_mode as a side
        effect.
        """
        if mode != "Auto":
            self._release_fan_assist()
            return room_positions

        # Fan-assist is for when the system is NOT actively conditioning. If the
        # compressor/burner is running, the priority pass already handles it.
        if hvac_action in ("cooling", "heating"):
            self._release_fan_assist()
            return room_positions

        # Decide which way to redistribute. Prefer whichever setpoint the house
        # is currently violating; in dual-setpoint (heat_cool) idle this picks
        # the real problem. Heating takes precedence only if a room is actually
        # below the heat setpoint and none is above the cool setpoint.
        heating = self._fan_assist_direction(target_cool, target_heat)
        if heating is None:
            self._release_fan_assist()
            return room_positions

        # Dry-coil lockout (cooling direction only). For the first
        # FAN_ASSIST_COIL_DRY_MIN minutes after the compressor stops, the
        # evaporator is still shedding condensate; recirculating over it would
        # re-evaporate that water into the house. Hold the blower until the
        # coil has drained. Heating has no condensate, so it's never gated.
        if not heating and self._cooling_ended_at is not None:
            since_min = (self.datetime()
                         - self._cooling_ended_at).total_seconds() / 60.0
            if since_min < FAN_ASSIST_COIL_DRY_MIN:
                self.log(f"  FAN-ASSIST: coil-dry lockout "
                         f"({since_min:.0f}/{FAN_ASSIST_COIL_DRY_MIN:.0f}m "
                         f"since cooling stopped) — holding blower")
                self._release_fan_assist()
                return room_positions

        setpoint = target_heat if heating else target_cool

        def off_by(t):
            return (setpoint - t) if heating else (t - setpoint)

        # Beneficiaries: occupied rooms far enough off-target to warrant it.
        # Activation uses the SAME measured per-room margin as the priority
        # pass (_room_margin — driven by supply-air penalty and delivery/
        # capacity handicap), not a flat threshold. Without this, a known-
        # stuck room (sensor.smart_vent_delivery_handicap already flagging
        # it) still had to wait for the same flat FAN_ASSIST_OVER=2.0F gap
        # as every other room before fan-assist would even consider it,
        # even though the priority pass (active only while the compressor
        # runs) would have engaged it earlier. The house spends real idle/
        # fan time between cooling cycles, so this axis needs to be live
        # here too, not just during active "cooling"/"heating".
        beneficiaries = []  # (off, key, temp, escalated)
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                occ_entity = sensors.get("occupancy")
                off = off_by(temp)
                # Same occupancy override as the priority pass: a hot room
                # gets fan-assist even if unoccupied (see OCCUPANCY_OVERRIDE_OVER).
                # Zone-presence contention (lever A): the threshold is RELATIVE
                # for rooms in a vacant zone, via the SAME single shared helper
                # the priority pass uses (recurring-bug-class guard).
                _occ_override = self._effective_occupancy_override(
                    zone_name, key, heating)
                if occ_entity and self.get_state(occ_entity) != "on":
                    if off < _occ_override:
                        continue
                margin = self._room_margin(key, heating, base_margin=FAN_ASSIST_OVER)
                if off < margin:
                    continue
                escalated = (off >= PRIORITY_ESCALATE_OVERRIDES.get(key, PRIORITY_ESCALATE_OVER)
                             or self._delivery_penalty.get(key, 0.0)
                             >= DELIVERY_ESCALATE_PENALTY)
                beneficiaries.append((off_by(temp), key, temp, escalated))

        beneficiaries.sort(reverse=True)  # worst-off first
        beneficiary_keys = {b[1] for b in beneficiaries}

        engaged_any = False
        for off, key, temp, escalated in beneficiaries:
            zone_name, room_name = key
            # Is there banked oppositely-conditioned air to move? Donors clearly
            # more comfortable than this room and NOT themselves beneficiaries.
            donors = []
            for zn, z in ZONES.items():
                for rn in z["rooms"]:
                    if (zn, rn) == key or (zn, rn) in beneficiary_keys:
                        continue
                    droom = ZONES[zn]["rooms"][rn]
                    dtemp = self._read_temp(droom["temp"])
                    if dtemp is None:
                        continue
                    # Zone-presence contention (lever B): a donor in a VACANT
                    # zone can be trusted with less proven margin, waiving up to
                    # ZONE_VACANCY_DONOR_RELAX * contention of the flat
                    # FAN_ASSIST_DONOR_COOLER_BY (but never below the
                    # ZONE_VACANCY_DONOR_MIN_COOLER_F thermodynamic floor).
                    d_cooler_by = self._donor_cooler_by(
                        zn, FAN_ASSIST_DONOR_COOLER_BY, heating)
                    if heating:
                        useful = dtemp >= temp + d_cooler_by
                    else:
                        useful = dtemp <= temp - d_cooler_by
                    if useful:
                        docc = droom.get("occupancy")
                        doccupied = (self.get_state(docc) == "on"
                                     if docc else False)
                        donors.append(((zn, rn), doccupied, dtemp))

            if not donors:
                continue  # nothing banked to move -> running the fan is pointless

            # Engage: fan on, needy room wide open, choke the banked rooms so
            # their air is redirected to where it's needed.
            engaged_any = True
            room_positions[key] = 100
            # unoccupied first; then most-comfortable donor (warmest when
            # heating, coolest when cooling) gives up air most safely.
            donors.sort(key=lambda x: (x[1], -x[2] if heating else x[2]))
            throttled = 0
            # Escalated (far-over-setpoint or measured delivery-handicap)
            # beneficiaries get MORE donors thrown at them, same intent as
            # the priority pass's escalation — a stuck room needs every bit
            # of banked air we can redirect, not just the standard allotment.
            max_donors = (PRIORITY_MAX_DONORS * 2 if escalated
                          else PRIORITY_MAX_DONORS)
            # Donor throttle position mirrors the priority pass: 50% normally
            # (donor keeps half its own banked air, still gives up real CFM),
            # fully closed (0%) only when escalated. Previously this always
            # closed to 0% regardless of escalation — MORE aggressive than
            # the priority pass despite fan-assist being the lower-stakes,
            # compressor-off scenario (no freeze risk, no reason to be more
            # aggressive here than during active cooling). Fixed 2026-07-26:
            # unconditionally slamming every donor to 0% also fought the
            # backpressure safety net, which would force-reopen them to 50%
            # on the very next check anyway once too many vents were closed
            # — wasted command + log noise for no benefit.
            donor_pos = (PRIORITY_DONOR_POS_ESCALATED if escalated
                         else PRIORITY_DONOR_POS)
            for dkey, _docc, _dtemp in donors:
                if throttled >= max_donors:
                    break
                room_positions[dkey] = donor_pos
                throttled += 1

            kind = "warm" if heating else "cold"
            tag = " [ESCALATED]" if escalated else ""
            self.log(f"  FAN-ASSIST {room_name} ({temp:.1f}F, off{off:+.1f}, "
                     f"{'heat' if heating else 'cool'}, hvac={hvac_action})"
                     f"{tag}: "
                     f"blower ON, redirecting banked {kind} air from "
                     f"{throttled} room(s)")

        if engaged_any:
            self._engage_fan_assist()
        else:
            self._release_fan_assist()

        return room_positions

    def _fan_assist_direction(self, target_cool, target_heat):
        """Decide fan-assist redistribution direction from current room temps.

        Returns True (heat: move warm air to cold rooms), False (cool: move cold
        air to hot rooms), or None (nothing to do). Looks at which setpoint
        OCCUPIED rooms are actually violating; if both, the larger violation
        wins. This keeps a single hallway thermostat's idle state from leaving a
        room stranded on either side of the deadband.
        """
        worst_hot = 0.0   # most over the cool setpoint
        worst_cold = 0.0  # most under the heat setpoint
        for _zone_name, zone in ZONES.items():
            for _room_name, sensors in zone["rooms"].items():
                occ = sensors.get("occupancy")
                if occ and self.get_state(occ) != "on":
                    continue
                t = self._read_temp(sensors["temp"])
                if t is None:
                    continue
                if target_cool is not None:
                    worst_hot = max(worst_hot, t - target_cool)
                if target_heat is not None:
                    worst_cold = max(worst_cold, target_heat - t)
        if worst_hot < FAN_ASSIST_OVER and worst_cold < FAN_ASSIST_OVER:
            return None
        return worst_cold > worst_hot

    def _heartbeat(self):
        """Stamp the heartbeat sensor with the current time + brief status.

        Written every control loop. An external watchdog reads last_changed /
        the timestamp and alerts if it goes stale (app crashed or stopped
        looping). Best-effort: a heartbeat failure must never break control.
        """
        try:
            # aware=True so the ISO string carries the UTC offset. A naive
            # local timestamp is misread by HA's Prometheus export (it assumes
            # UTC), which shifted the exported epoch by the local offset and
            # made any VictoriaMetrics "heartbeat age" panel read garbage. The
            # watchdog reads HA's last_changed so it was unaffected, but the
            # exported metric must be correct for Grafana to use it.
            now = self.datetime(aware=True)
            enabled = self.get_state(ENABLED_SWITCH)
            mode = self.get_state(MODE_SELECT)
            self.set_state(
                HEARTBEAT_ENTITY,
                state=now.isoformat(),
                attributes={
                    "device_class": "timestamp",
                    "friendly_name": "Smart Vent Controller Heartbeat",
                    "icon": "mdi:heart-pulse",
                    "enabled": enabled,
                    "vent_mode": mode,
                    "cycle_interval_s": CYCLE_INTERVAL,
                },
            )
        except Exception as e:
            self.log(f"heartbeat write failed (non-fatal): {e}")

    def _engage_fan_assist(self):
        """Turn the air handler fan to 'on', tracking that WE did it.

        Goes through the ecobee_enhanced integration's real cloud API
        (setHold with a "fan" param, no heat/coolHoldTemp — a pure fan
        hold) instead of climate/set_fan_mode against the HomeKit
        Controller entity. HomeKit fan-mode writes are a documented HA
        bug (home-assistant/core#92010): ANY fan_mode change through
        HomeKit forces an indefinite TEMPERATURE hold too, silently
        knocking the ecobee off its schedule until someone notices and
        presses Resume Program. 2026-08-09 incident: this app's own
        FAN-ASSIST cycles were doing exactly that, 2-4x/day, undetected
        for hours at a time. The ecobee_enhanced fan hold sets fan-only
        (isTemperatureAbsolute/Relative both false), so the schedule's
        setpoints keep running underneath it.
        """
        if getattr(self, "_fan_assist_active", False):
            return
        current = self.get_state(FAN_ENTITY, attribute="fan_mode")
        if current == "on":
            # Already on (user or schedule); don't claim ownership so we won't
            # turn it off later and stomp their setting.
            return
        self.log("  FAN-ASSIST: setting ecobee fan hold -> on (via ecobee_enhanced, not HomeKit)")
        # Fire-and-forget — see _set_vent for why (2026-08-08 thread-freeze
        # incident). This callback also blocks the same pinned worker
        # thread as the vent-position calls.
        self.call_service("ecobee_enhanced/set_fan_hold",
                          fan_mode="on", hold_type="indefinite", hass_timeout=8,
                          callback=self._service_call_done)
        self._fan_assist_active = True

    def _release_fan_assist(self):
        """Clear the fan-only hold we created, via resume_top_event.

        resumeAll=false pops ONLY the fan hold we pushed, leaving any
        real user hold (e.g. Hold Away) underneath untouched. Previously
        this called climate/set_fan_mode -> "auto" against the HomeKit
        entity, which does NOT clear the hold ecobee's firmware created
        on engage — that "auto" write is itself just another HomeKit
        command, so the hold silently persisted for hours past release.
        """
        if not getattr(self, "_fan_assist_active", False):
            return
        self.log("  FAN-ASSIST: releasing fan hold (resume_top_event, via ecobee_enhanced)")
        self.call_service("ecobee_enhanced/resume_top_event",
                          hass_timeout=8,
                          callback=self._service_call_done)
        self._fan_assist_active = False

    # ── Setpoint nudge (the TRIGGER axis) ─────────────────────────────────────
    # Makes the compressor escalate by temporarily moving the thermostat
    # setpoint when an OCCUPIED room's measured excess over its margin warrants
    # it — the measured-axis complement to fan-assist (which solves airflow
    # redistribution once the compressor runs). This is the ONLY lever that
    # reaches the ecobee, because the stage-2 differential is manual-only (not
    # API-settable); see the constants block for the full rationale.
    #
    # Ownership state machine. We match LIVE readback against what WE last wrote
    # (_sp_commanded_*). Note this deliberately does NOT use hold_climate or
    # schedule_status: an empty hold_climate (raw temperature hold) is produced
    # by BOTH our set_hold_temperature call AND a user's manual setpoint change,
    # so it cannot tell our write apart from theirs. Value-matching the
    # setpoints is the only reliable discriminator.
    #
    #   NOT owned:
    #     - worst_excess >= ENGAGE  -> capture baseline_* = current live setpoints
    #       (the user's own effective setpoint, whatever it is), compute nudge,
    #       write, _sp_owned = True.
    #     - else                    -> no-op.
    #   Owned + readback matches (on the axis we moved):
    #     - clear _sp_mismatch_since.
    #     - worst_excess <= RELEASE -> resume_top_event, clear all _sp_* state.
    #     - deeper nudge warranted AND dwell elapsed -> re-write the LARGER
    #       nudge, still off the ORIGINAL baseline (never off the already-nudged
    #       value — that would ratchet away unboundedly).
    #     - else                    -> no-op.
    #   Owned + readback does NOT match:
    #     - _sp_mismatch_since None -> set it to now, take NO action. (Fresh
    #       mismatch right after our own write is the in-flight echo: the ecobee
    #       cloud poll is up to 3 min behind, so it is EXPECTED and must not be
    #       believed. Same bug class as the vent MANUAL_OVERRIDE_CONFIRM_SEC
    #       debounce / _confirm_manual_override.)
    #     - mismatch persisted >= CONFIRM  -> the USER changed it. _sp_owned =
    #       False, clear state. Do NOT resume, do NOT restore the baseline. The
    #       user's new value becomes the baseline for any FUTURE engagement.
    #     - else                     -> keep waiting.
    #
    # TRAP 1 (heatCoolMinDelta): the ecobee enforces a min 6.0F gap between the
    # heat and cool setpoints in heat_cool/auto mode, and REJECTS or silently
    # auto-adjusts a write that violates it. So when we nudge cool DOWN we must
    # also drag heat DOWN, and when we nudge heat UP we must also drag cool UP.
    # Only coupled in a dual-setpoint mode; otherwise the other axis passes
    # through at its current live value.
    #
    # TRAP 2 (never pop the user's hold): resume_top_event pops whatever event
    # is on TOP of the ecobee's event stack. If our netTransition hold already
    # auto-expired (or the user resumed it), the top event may now be the
    # USER's own hold. Therefore we NEVER call resume_top_event unless the live
    # readback still matches our _sp_commanded_* values — the "readback doesn't
    # match" branch exits WITHOUT resuming. This is the single most important
    # safety rule in this design. It is enforced structurally: _release_setpoint
    # is only ever called from the "readback matches" branch. That includes the
    # idle/fan path: the original unguarded release there (released whenever the
    # compressor happened to drop to idle, with NO readback check) was unsafe
    # and is gone — while idle we now run the SAME owned-branch match/mismatch
    # logic, so a release only happens when readback still matches AND the room
    # has actually recovered.
    def _release_setpoint_nudge(self):
        """Pop our own setpoint hold, clearing ownership state.

        SAFETY (TRAP 2): this must ONLY be called from the branch where the live
        readback still matches what WE commanded. At that moment OUR hold is
        still the top event, so resume_top_event (resumeAll=false) pops exactly
        ours and leaves any user hold underneath untouched. If our hold had
        already auto-expired (nextTransition fired) or the user resumed it, the
        readback would differ from _sp_commanded_* and we take the readback-
        mismatch branch instead — which exits WITHOUT ever reaching here — so a
        user hold already on top of the stack can never be popped by us. There
        is exactly ONE call site reachable while idle/fan, and it is guarded by
        the same readback-match check (see _apply_setpoint_nudge).
        """
        self.log(f"  SETPOINT-NUDGE: releasing (resume_top_event) — our hold "
                 f"is still the top event, safe to pop")
        # WRITE-AHEAD: persist the relinquishment BEFORE issuing the release, so
        # a crash between these two lines cannot leave a live hold behind with
        # no persisted record (the amnesia the reset would then ratchet on).
        self._persist_nudge_state(owned=False)
        # Fire-and-forget — see _set_vent for why (pinned-thread freeze
        # incident). Same callback discipline as fan-assist.
        self.call_service("ecobee_enhanced/resume_top_event",
                          hass_timeout=8,
                          callback=self._service_call_done)
        # Ownership cleared AFTER issuing the call (fire-and-forget): the state
        # must reflect that we no longer "own" a hold at the moment we give it
        # back to the ecobee.
        self._sp_owned = False
        self._sp_commanded_cool = None
        self._sp_commanded_heat = None
        self._sp_baseline_cool = None
        self._sp_baseline_heat = None
        self._sp_last_write_ts = None
        self._sp_mismatch_since = None
        self._sp_heating = None

    def _write_setpoint_nudge(self, heat_temp_f, cool_temp_f):
        """Issue a setpoint hold via ecobee_enhanced (fire-and-forget).

        The service schema REQUIRES both heat_temp_f and cool_temp_f, so to
        "leave an axis untouched" we still send its current live value. Guard
        against a missing axis (single-setpoint cool/heat mode reads the other
        setpoint as None): skipping without writing is safe — the thermostat
        this app targets lives in heat_cool, where both axes are always present.

        hold_type MUST be "nextTransition", NOT "indefinite": it makes the
        ecobee itself expire our hold at the next scheduled comfort transition —
        a built-in dead-man's switch. If this app ever dies mid-nudge (it has
        frozen before; see the _set_vent pinned-thread freeze bug), an
        indefinite hold would be stuck on the user's thermostat forever. That is
        the single worst outcome and this choice prevents it.
        """
        if heat_temp_f is None or cool_temp_f is None:
            self.log(f"  SETPOINT-NUDGE: skipping write — missing setpoint axis "
                     f"(heat={heat_temp_f}, cool={cool_temp_f})")
            return
        self.call_service(
            "ecobee_enhanced/set_hold_temperature",
            heat_temp_f=float(heat_temp_f),
            cool_temp_f=float(cool_temp_f),
            hold_type="nextTransition",
            hass_timeout=8,
            callback=self._service_call_done,
        )

    # ── Setpoint-nudge ownership persistence ──────────────────────────────────
    # Restart-amnesia/ratchet fix (2026-09-01). Ownership must survive an app
    # restart with VALIDATED restore: a persisted record is only re-adopted when
    # the live readback corroborates it, otherwise it is discarded and today's
    # existing behavior (adopt the live value as the user's baseline) runs.

    def _nudge_state_path(self):
        """Return the absolute path of the nudge-ownership state file.

        Computed once in initialize() (_nudge_state_file) and cached. We do NOT
        fall back to deriving it from the module here on purpose: production
        initialize() always sets the path (so production persistence always
        works), and any code that never ran initialize() (e.g. an offline test
        harness that only exercises _apply_setpoint_nudge) must not silently
        write a state file into the app directory — returning None makes both
        persist and restore safe no-ops there.
        """
        return getattr(self, "_nudge_state_file", None)

    def _persist_nudge_state(self, owned, commanded_cool=None, commanded_heat=None,
                             baseline_cool=None, baseline_heat=None, heating=None):
        """Atomically persist the full nudge-ownership record to disk.

        WRITE-AHEAD: callers invoke this BEFORE issuing any setHold/resume
        service call. State is serialized as ONE record, so a crash can never
        leave a half-restored pair (the ecobee heatCoolMinDelta is 6F and this
        house sits exactly at that minimum gap, so a half-restored pair would be
        silently rejected by a later write).

        `owned` is True for engage/keep/deepen, False for relinquish/release.
        When relinquishing we persist owned=False WITHOUT the commanded values,
        so a restore can never re-adopt after a clean (non-ratchet) exit — the
        absence of a corroborating commanded record forces discard. The record's
        commanded fields are written as None when owned=False so a reader cannot
        mistake a stale value for ours.

        All I/O is defensive: any exception is caught and logged, and NEVER
        crashes the control loop or initialize(). A failed persist is a
        degraded-but-safe condition (the dead-man's switch bounds it), not fatal.
        """
        try:
            path = self._nudge_state_path()
            if path is None:
                return
            if getattr(self, "_nudge_persist_disable", False):
                self.log("  SETPOINT-NUDGE: persistence disabled (test); "
                         "skipping state write")
                return
            commanded_cool = (None if commanded_cool is None
                              else float(commanded_cool))
            commanded_heat = (None if commanded_heat is None
                              else float(commanded_heat))
            baseline_cool = (None if baseline_cool is None
                             else float(baseline_cool))
            baseline_heat = (None if baseline_heat is None
                             else float(baseline_heat))
            record = {
                "version": NUDGE_STATE_VERSION,
                "owned": bool(owned),
                # ISO-8601 UTC timestamp of THIS command, so a restore can
                # still judge whether the confirm window is open.
                "commanded_at": self.datetime().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "commanded_cool": commanded_cool,
                "commanded_heat": commanded_heat,
                "baseline_cool": baseline_cool,
                "baseline_heat": baseline_heat,
                "heating": (None if heating is None else bool(heating)),
            }
            payload = json.dumps(record)
            # Atomic write: temp file in the same dir + os.replace(). A reader
            # sees either the old or the new file, never a partial record.
            fd, tmp = tempfile.mkstemp(prefix="nudge_state_",
                                       dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            except BaseException:
                # Best-effort cleanup of the temp file on failure.
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except (OSError, IOError):
                    pass
                raise
        except Exception as e:  # noqa: BLE001 - defensive: never crash the loop
            self.log(f"  SETPOINT-NUDGE: failed to persist ownership state — "
                     f"degraded but safe, one-cycle dead-man's-switch may "
                     f"replay: {e}")

    def _restore_nudge_ownership(self):
        """Load the persisted record in initialize() and conditionally re-adopt.

        Set on the app the ownership attributes the record describes, then
        defer the readback MATCH decision to the first control_loop cycle (see
        control_loop + _validate_restored_nudge): get_state() can be
        unavailable/racy the instant the app starts during a restart, so we
        cannot trust a read taken synchronously here. The re-adoption here is
        therefore a provisional "_sp_owned=True pending readback validation",
        flagged by _nudge_restore_pending.

        If the record is missing, corrupt, unparseable, missing fields, an
        unknown version, or a clean 'owned=False' relinquishment (release /
        user-override / hold-expired), we clear ownership state and return —
        today's existing behavior (adopt the live value as the user's baseline)
        then runs, which is the desired fall-through for 'the user changed it
        while the app was down' and 'the hold expired via nextTransition during
        downtime'.

        NO release/resume call is ever issued here.
        """
        self._nudge_restore_pending = False
        try:
            path = self._nudge_state_path()
            if path is None:
                return
            if not os.path.exists(path):
                return  # no record -> normal first start / file lost (accepted)
            with open(path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state record not a JSON object")
            if data.get("version") != NUDGE_STATE_VERSION:
                raise ValueError("unknown state version")
            if not data.get("owned"):
                # A clean relinquish/release wrote owned=False, or the previous
                # run correctly discarded on a mismatch: not re-adopting is
                # correct either way.
                return
            commanded_at = data.get("commanded_at")
            cmd_ts = None
            if isinstance(commanded_at, str):
                try:
                    cmd_ts = datetime.strptime(commanded_at,
                                               "%Y-%m-%dT%H:%M:%SZ")
                except (ValueError, TypeError):
                    cmd_ts = None
            if cmd_ts is None:
                raise ValueError("missing/unparseable commanded_at timestamp")

            bas_cool = data.get("baseline_cool")
            bas_heat = data.get("baseline_heat")
            cmd_cool = data.get("commanded_cool")
            cmd_heat = data.get("commanded_heat")
            heating = data.get("heating")
            # Baseline AND commanded values must be present and numeric on BOTH
            # axes for a re-adoption (heatCoolMinDelta pair integrity: restore
            # both together or not at all — a half-restored pair is silently
            # rejected by ecobee writes). heating must be a bool to pick the
            # moved axis for the readback match.
            if bas_cool is None or bas_heat is None:
                raise ValueError("missing baseline axis")
            if cmd_cool is None or cmd_heat is None:
                raise ValueError("missing commanded axis")
            if heating is None:
                raise ValueError("missing heating direction")
            bas_cool, bas_heat = float(bas_cool), float(bas_heat)
            cmd_cool, cmd_heat = float(cmd_cool), float(cmd_heat)
            heating = bool(heating)
            self.log(f"  SETPOINT-NUDGE: found persisted ownership "
                     f"(commanded cool {cmd_cool:.1f} heat {cmd_heat:.1f}, "
                     f"baseline cool {bas_cool:.1f} heat {bas_heat:.1f}, "
                     f"commanded_at {commanded_at}) — pending live-readback "
                     f"validation on the first control loop")

            # Provisional re-adopt. Set ALL ownership state from the record; the
            # first control_loop cycle will corroborate (or discard) it against
            # the live readback before any pass below uses _sp_owned.
            self._sp_owned = True
            self._sp_commanded_cool = cmd_cool
            self._sp_commanded_heat = cmd_heat
            self._sp_baseline_cool = bas_cool
            self._sp_baseline_heat = bas_heat
            self._sp_last_write_ts = cmd_ts
            self._sp_mismatch_since = None
            self._sp_heating = heating
            self._sp_restore_commanded_at = cmd_ts
            self._nudge_restore_pending = True
        except Exception as e:  # noqa: BLE001 - defensive discard, never crash
            self.log(f"  SETPOINT-NUDGE: persisted ownership state corrupt or "
                     f"invalid, DISCARDING — adopting live setpoints as the "
                     f"user's baseline: {e}")
            self._sp_owned = False
            self._sp_commanded_cool = None
            self._sp_commanded_heat = None
            self._sp_baseline_cool = None
            self._sp_baseline_heat = None
            self._sp_last_write_ts = None
            self._sp_mismatch_since = None
            self._sp_heating = None

    def _validate_restored_nudge(self, live_cool, live_heat):
        """Corroborate a re-adopted persisted record against the LIVE readback.

        Called once, on the first control_loop cycle after initialize() loaded a
        record. Re-adopts full ownership ONLY IF the live readback corroborates
        the persisted record:
          - readback matches the persisted commanded value on the moved axis
            (within SETPOINT_NUDGE_TOLERANCE_F) -> keep full ownership. This is
            the ratchet fix: the app now KNOWS the 66 is ITS OWN hold and that
            its true baseline is 72.
          - OR the confirm window (SETPOINT_NUDGE_CONFIRM_SEC from the persisted
            command time) is still open AND readback still matches the PRIOR
            (pre-nudge) value -> keep ownership, still in-flight (the nudge
            hasn't echoed back yet / the user's schedule value is still live).
          - ANYTHING ELSE -> DISCARD silently and fall through: the live value
            is adopted as the user's baseline by today's existing behavior.
            This covers 'the user changed it while the app was down' and 'the
            hold expired via nextTransition during downtime'.
        NO release/resume service call is issued here (releasing on an
        unexplained mismatch would clobber a genuine user hold — the REJECTED
        option).
        """
        # Reuse the EXISTING _nudge_readback_matches so restore and steady-state
        # ownership can never disagree (recurring-bug-class guard). It compares
        # self._sp_commanded_* on the moved axis; a persisted record set those,
        # so the predicate works unchanged.
        if self._sp_owned and self._sp_heating is not None \
                and self._nudge_readback_matches(self._sp_heating,
                                                 live_cool, live_heat):
            self.log("  SETPOINT-NUDGE: restored ownership VALIDATED — live "
                     "readback matches persisted commanded value; re-adopting "
                     f"baseline cool {self._sp_baseline_cool:.1f} heat "
                     f"{self._sp_baseline_heat:.1f}")
            if hasattr(self, "_sp_restore_commanded_at"):
                del self._sp_restore_commanded_at
            return

        # Readback did NOT match the persisted commanded value. Check whether the
        # confirm window from the persisted command time is still open.
        cmd_ts = getattr(self, "_sp_restore_commanded_at", None)
        in_flight = False
        if cmd_ts is not None and self._sp_heating is not None:
            now = self.datetime()
            if (now - cmd_ts).total_seconds() < SETPOINT_NUDGE_CONFIRM_SEC:
                # Window open. Re-adopt as in-flight ONLY if the live readback
                # still matches the PRIOR value (the user's pre-nudge baseline),
                # i.e. the nudge simply hasn't echoed/applied yet.
                if not self._sp_heating:
                    matches_prior = (live_cool is not None
                                     and abs(live_cool - self._sp_baseline_cool)
                                     <= SETPOINT_NUDGE_TOLERANCE_F)
                else:
                    matches_prior = (live_heat is not None
                                     and abs(live_heat - self._sp_baseline_heat)
                                     <= SETPOINT_NUDGE_TOLERANCE_F)
                if matches_prior:
                    in_flight = True
                    self.log("  SETPOINT-NUDGE: restored ownership re-adopted "
                             "as IN-FLIGHT — confirm window open and readback "
                             "still matches the pre-nudge value")

        if not in_flight:
            # Corrupt/stale/unexplained mismatch: DISCARD silently. Do NOT issue
            # any release/resume. Existing behavior adopts the live value as the
            # user's baseline on the next pass.
            self.log("  SETPOINT-NUDGE: restored ownership DISCARDED — live "
                     "readback does not corroborate the persisted record, so "
                     "adopting live as the user's baseline")
            self._sp_owned = False
            self._sp_commanded_cool = None
            self._sp_commanded_heat = None
            self._sp_baseline_cool = None
            self._sp_baseline_heat = None
            self._sp_last_write_ts = None
            self._sp_mismatch_since = None
            self._sp_heating = None
            if hasattr(self, "_sp_restore_commanded_at"):
                del self._sp_restore_commanded_at

    def _nudge_readback_matches(self, heating, live_cool, live_heat):
        """True iff live readback matches what we last commanded on the moved axis.

        Single source of truth for the readback-match condition shared by
        _apply_setpoint_nudge (ownership keep/release) and _active_nudge_baseline
        (whether to reference the pre-nudge baseline for vent scoring). The moved
        axis is the one the nudge actually changed ('heating' True -> heat axis,
        False -> cool axis); the other axis may be coupled (TRAP 1 heatCoolMinDelta)
        but ownership pivots only on the moved axis.

        Pure refactor target: _apply_setpoint_nudge's owned branch computes this
        inline; routing it through here (identical expression) keeps the two
        consumers from ever drifting apart, which is the exact recurring bug class
        this file guards against.
        """
        if not heating:
            return (live_cool is not None
                    and abs(live_cool - self._sp_commanded_cool)
                    <= SETPOINT_NUDGE_TOLERANCE_F)
        else:
            return (live_heat is not None
                    and abs(live_heat - self._sp_commanded_heat)
                    <= SETPOINT_NUDGE_TOLERANCE_F)

    def _active_nudge_baseline(self, target_cool, target_heat):
        """Return (baseline_cool, baseline_heat) iff a setpoint nudge is active
        AND its live readback matches what we commanded.

        Vent scoring must reference the USER's effective (pre-nudge BASELINE)
        setpoints while a nudge is actively holding the thermostat below/above
        them. The vents aim at how the house should FEEL, while the compressor is
        separately being hammered harder by the nudge (so the nudge's own
        worst_excess and _update_delivery_penalties deliberately stay on LIVE
        setpoints — see callers). Without this substitution every room reads as
        far over the artificially-nudged setpoint during an active nudge and pins
        at 100%, defeating all redistribution.

        Returns None — so callers fall back to the LIVE setpoints, giving
        byte-identical behavior whenever no nudge is trusted live — unless we own
        a nudge in the exact 'owned AND readback matches' keep-ownership state
        _apply_setpoint_nudge uses:
          - not owned                            -> None
          - owned but _sp_heating missing        -> None (no axis to compare)
          - owned but baseline missing           -> None (defensive)
          - owned + FRESH readback mismatch      -> None. This is the in-flight
            echo/confirm window. Matching the existing confirm-window semantics
            (SETPOINT_NUDGE_CONFIRM_SEC), we deliberately do NOT act on an
            unconfirmed reading — the nudge may be about to relinquish.
          - owned + readback matches             -> (baseline_cool, baseline_heat)
        The readback-match condition is EXACTLY the one _apply_setpoint_nudge
        uses to KEEP ownership (shared _nudge_readback_matches predicate), so the
        two can never disagree about whether the nudge is trusted.
        """
        if not getattr(self, "_sp_owned", False):
            return None
        heating = self._sp_heating
        if heating is None:
            return None
        if self._sp_baseline_cool is None or self._sp_baseline_heat is None:
            return None
        if not self._nudge_readback_matches(heating, target_cool, target_heat):
            return None
        return (self._sp_baseline_cool, self._sp_baseline_heat)

    def _apply_setpoint_nudge(self, hvac_mode, hvac_action, target_cool,
                              target_heat, mode="Auto"):
        """Temporarily move the thermostat setpoint to force compressor escalation.

        Computes `worst_excess` = max over OCCUPIED rooms of
        (off_target - _room_margin), the SAME measured quantity _zone_contention
        already uses for other zones (reusing its exact idiom to avoid inventing
        a parallel axis). A room counts as occupied using the SAME determination
        the priority pass uses, including the PIR-false-negative effective-
        occupancy-override path (_effective_occupancy_override). A room in a
        VACANT zone can never drive a nudge.

        nudge_amount = clamp(worst_excess * GAIN, 0, MAX), quantized DOWN to a
        multiple of STEP. Cooling: commanded_cool = baseline_cool - nudge_amount.
        Heating: commanded_heat = baseline_heat + nudge_amount. Fully symmetric.

        Only acts in Auto mode (the controller's enabled gate is already handled
        by control_loop, but this re-guards on mode for safety). The DIRECTION of
        the nudge comes from the active HVAC action (cooling -> lower cool
        setpoint -> heating=False; heating -> raise heat setpoint ->
        heating=True). While idle/fan there is no active axis to derive a
        direction from, so we fall back to the recorded _sp_heating of any nudge
        we already own: an idle drop must NOT short-circuit into an unguarded
        release — it instead continues into the same owned state machine, so a
        between-cycles idle transition can neither pop the user's hold (TRAP 2)
        nor drop a live nudge just because the compressor happens to be between
        cycles. Deepening happens only while actively conditioning; a brand-new
        nudge is never engaged while idle.
        Mutates no state it doesn't own (all _sp_*).
        """
        if mode != "Auto":
            return
        if hvac_action == "cooling" and target_cool is not None:
            heating = False
        elif hvac_action == "heating" and target_heat is not None:
            heating = True
        else:
            # Not actively conditioning (idle/fan). There is no live axis to
            # derive a direction from, so fall back to the direction of any nudge
            # we already own. The ORIGINAL code released here with NO readback
            # check, which was unsafe two ways: (1) when the compressor satisfies
            # and drops to idle while a room is still hot, releasing on every
            # idle transition lets the room reheat and the nudge re-engage next
            # cycle (the oscillator loop this mechanism exists to prevent); (2)
            # worse, if the USER had changed the setpoint (their hold now on top),
            # releasing would pop THEIR hold, bypassing the _sp_mismatch_since /
            # CONFIRM_SEC machinery entirely (TRAP 2 violation). So while idle we
            # run the SAME readback-guarded ownership logic below: never resume on
            # a mismatch, only release on a genuine recovery, and never deepen.
            # If we own nothing, there is nothing to do here — return as before.
            if not getattr(self, "_sp_owned", False):
                return
            if self._sp_heating is None:
                # Defensive: we own a nudge but somehow have no recorded
                # direction — nothing safe to compare, so leave the hold alone.
                return
            heating = self._sp_heating

        # True only while the compressor/burner is actually running. Deepening a
        # nudge (and engaging a fresh one) is gated on this below.
        actively_conditioning = (hvac_action == "cooling"
                                 or hvac_action == "heating")

        # Worst excess over OCCUPIED rooms, measured exactly like _zone_contention
        # (line ~1530): off_target - _room_margin, clamped at >= 0.
        worst_excess = 0.0
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                occ_entity = sensors.get("occupancy")
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                is_occupied = ((not occ_entity)
                               or self.get_state(occ_entity) == "on")
                # Occupancy gate mirrors _apply_priority_rooms: an OCCUPIED room
                # (or no sensor => assumed occupied) counts; an unoccupied room
                # is NOT an occupant needing the compressor to escalate unless
                # its PIR false-negative override applies (_effective_occupancy_
                # override — the shared decision the priority and fan-assist
                # passes use). A room in a VACANT zone can NEVER drive a nudge,
                # categorically: an empty room in a zone nobody is in has no
                # occupant to save, so letting it escalate the compressor would
                # just push the whole house's setpoint for nobody. So we hard-
                # exclude vacant zones BEFORE the override path — that override
                # is only meaningful in an occupied zone, where it reduces to
                # the bare OCCUPANCY_OVERRIDE_OVER (matching _apply_priority_rooms).
                if not is_occupied:
                    if self._zone_is_vacant(zone_name):
                        continue
                    _override = self._effective_occupancy_override(
                        zone_name, key, heating)
                    if self._off_target(room_name, temp, heating) < _override:
                        continue
                # NOTE: a donor_only room is NOT skipped here (deliberately
                # different from _apply_priority_rooms). donor_only only means
                # "never a BENEFICIARY of vent REDISTRIBUTION" — it does not mean
                # the room can't burn its occupant. A genuinely hot donor-only
                # room (Main Bedroom) still needs the compressor to escalate, so
                # it is fully eligible to drive a nudge.
                off = self._off_target(room_name, temp, heating)
                margin = self._room_margin(key, heating)
                excess = off - margin
                if excess > worst_excess:
                    worst_excess = excess

        # ---------------------------------------------------------------- State
        now = self.datetime()
        # TRAP 1 coupling is only relevant in a dual-setpoint (heat_cool/auto)
        # mode. Read `dual` ONCE for this whole cycle; it drives both the engage
        # and any re-nudge so the two can never disagree about the gap.
        dual = hvac_mode in ("heat_cool", "auto")

        if not getattr(self, "_sp_owned", False):
            # NOT owned. Engage only if the worst occupied excess clears the
            # engage threshold (with hysteresis below via the release bound), AND
            # only while actually conditioning. While idle/fan we engage nothing:
            # engaging a brand-new setpoint hold on a compressor that isn't even
            # running would just push the whole house's setpoint for no reason
            # (the escalation a nudge drives only happens once it runs) — and it
            # would write-churn on every idle/fan cycle. The compressor will
            # re-engage on its own schedule and we can nudge then.
            if worst_excess < SETPOINT_NUDGE_ENGAGE_F:
                return
            if not actively_conditioning:
                return
            # Capture the baseline = the CURRENT live setpoints (the user's own
            # effective setpoint — schedule or their manual hold).
            baseline_cool = target_cool
            baseline_heat = target_heat
            commanded_cool, commanded_heat = self._commanded_setpoints(
                baseline_cool, baseline_heat, heating, worst_excess, dual)
            # WRITE-AHEAD: persist the INTENDED ownership state BEFORE issuing
            # the hold. A persisted intent whose readback never matches is safely
            # DISCARDED on restore; the reverse (a live hold with no persisted
            # record) is exactly the restart-amnesia ratchet bug this guards
            # against. So the file records state BEFORE the service call.
            self._persist_nudge_state(
                owned=True,
                commanded_cool=commanded_cool,
                commanded_heat=commanded_heat,
                baseline_cool=baseline_cool,
                baseline_heat=baseline_heat,
                heating=heating)
            self._write_setpoint_nudge(commanded_heat, commanded_cool)
            self._sp_owned = True
            self._sp_baseline_cool = baseline_cool
            self._sp_baseline_heat = baseline_heat
            self._sp_commanded_cool = commanded_cool
            self._sp_commanded_heat = commanded_heat
            self._sp_last_write_ts = now
            self._sp_mismatch_since = None
            self._sp_heating = heating
            self.log(f"  SETPOINT-NUDGE: engaged ({'cool' if not heating else 'heat'}) "
                     f"worst_excess {worst_excess:.2f}F, nudge to "
                     f"cool {commanded_cool:.1f}F heat {commanded_heat:.1f}F "
                     f"(baseline cool {baseline_cool:.1f} heat {baseline_heat:.1f})")
            return

        # ------------------------------------------------------------- Owned.
        live_cool = target_cool
        live_heat = target_heat

        # Which axis did we move? (The moved axis is the one we compare readback
        # against — the other axis may be coupled, but ownership pivots on the
        # active cooling/heating axis we actually changed.) Shared predicate so
        # ownership and vent-scoring baseline substitution can never disagree
        # about whether the nudge's readback is trusted.
        matches = self._nudge_readback_matches(heating, live_cool, live_heat)

        if not matches:
            # Readback does NOT match our commanded value.
            if self._sp_mismatch_since is None:
                # Fresh mismatch right after our own write = the in-flight echo
                # (ecobee cloud poll up to 3 min behind). Do NOT believe it this
                # cycle; do NOT act.
                self._sp_mismatch_since = now
                return
            if (now - self._sp_mismatch_since).total_seconds() \
                    >= SETPOINT_NUDGE_CONFIRM_SEC:
                # The mismatch has PERSISTED past the confirm window: the USER
                # changed the setpoint. Relinquish ownership WITHOUT resuming
                # (their new value / hold is now on top and must not be popped;
                # TRAP 2) and WITHOUT restoring the baseline (their new value
                # simply becomes the baseline for any future engagement).
                self.log(f"  SETPOINT-NUDGE: user changed setpoint (cool "
                         f"{self._sp_commanded_cool:.1f} -> {live_cool} live), "
                         f"relinquishing ownership without resuming")
                # Persist the relinquishment BEFORE clearing in-memory state, so
                # a crash mid-transition cannot leave a stale "we own it" record.
                # The user's live value becomes the baseline for any future
                # engagement once they release it back to schedule.
                self._persist_nudge_state(owned=False)
                self._sp_owned = False
                self._sp_commanded_cool = None
                self._sp_commanded_heat = None
                self._sp_baseline_cool = None
                self._sp_baseline_heat = None
                self._sp_last_write_ts = None
                self._sp_mismatch_since = None
                self._sp_heating = None
            # else: still within the confirm window — keep waiting, no action.
            return

        # Readback matches. Clear any pending mismatch record.
        self._sp_mismatch_since = None

        if worst_excess <= SETPOINT_NUDGE_RELEASE_F:
            # Satisfied (or room recovered) enough — pop our own hold. ONLY safe
            # because readback still matches (TRAP 2). Clears all _sp_* state.
            self._release_setpoint_nudge()
            self.log(f"  SETPOINT-NUDGE: released (worst_excess {worst_excess:.2f}F "
                     f"<= release {SETPOINT_NUDGE_RELEASE_F:.2f}F)")
            return

        # Still engaged and warranted. Re-nudge DEEPER (never shallower here —
        # release is the only way out of the band, per hysteresis) off the ORIGINAL
        # baseline, but only after the dwell so we don't fight the ecobee's own
        # staging (SETPOINT_NUDGE_DWELL_SEC >= compressor min-on), AND only while
        # actually conditioning. While idle/fan we do NOT deepen: an idle drop
        # gives us no evidence the current nudge is insufficient — the compressor
        # may simply be in its min-off protection window (ecobee waits 5 min
        # before letting the compressor restart), and hammering the setpoint
        # deeper mid-min-off wouldn't escalate anything. The hold simply rides out
        # the idle period and, if the room is still hot, the release gate below
        # does not trip, so we pick up again on the next real conditioning cycle.
        if not actively_conditioning:
            return
        new_cool, new_heat = self._commanded_setpoints(
            self._sp_baseline_cool, self._sp_baseline_heat, heating,
            worst_excess, dual)
        # A deeper nudge only when the new command is actually MORE aggressive on
        # the moved axis, so we never re-issue an identical (or shallower) hold.
        moved_new = new_cool if not heating else new_heat
        moved_old = (self._sp_commanded_cool if not heating
                     else self._sp_commanded_heat)
        if (heating and moved_new <= moved_old) \
                or (not heating and moved_new >= moved_old):
            # No deeper nudge warranted (or identical after quantization) — no-op.
            return
        if (now - self._sp_last_write_ts).total_seconds() \
                < SETPOINT_NUDGE_DWELL_SEC:
            return
        # Write the larger nudge, still off the ORIGINAL baseline.
        self._persist_nudge_state(
            owned=True,
            commanded_cool=new_cool,
            commanded_heat=new_heat,
            baseline_cool=self._sp_baseline_cool,
            baseline_heat=self._sp_baseline_heat,
            heating=heating)
        self._write_setpoint_nudge(new_heat, new_cool)
        self._sp_commanded_cool = new_cool
        self._sp_commanded_heat = new_heat
        self._sp_last_write_ts = now
        self._sp_mismatch_since = None
        self.log(f"  SETPOINT-NUDGE: deepened to cool {new_cool:.1f}F "
                 f"heat {new_heat:.1f}F (worst_excess {worst_excess:.2f}F)")

    def _commanded_setpoints(self, baseline_cool, baseline_heat, heating,
                             worst_excess, dual):
        """Compute (commanded_cool, commanded_heat) for a nudge off the baseline.

        Pure function (no state): returns the two setpoints to write for the
        given baseline and worst_excess, applying the gain/max quantized cap and
        the heatCoolMinDelta coupling (TRAP 1). `dual` (True in a heat_cool/auto
        mode) is passed in — computed ONCE per cycle by the caller — so this
        helper stays stateless and the two call sites can never disagree about
        whether the gap is enforced.

        NOTE the tuple is (commanded_cool, commanded_heat) — the same order both
        call sites unpack (`commanded_cool, commanded_heat = ...`). This is the
        reverse of _write_setpoint_nudge's (heat, cool) parameter order, which is
        why the call sites swap when handing off (`_write_setpoint_nudge(new_heat,
        new_cool)`). Do NOT reorder this return.
        """
        nudge = worst_excess * SETPOINT_NUDGE_GAIN
        nudge = max(0.0, min(nudge, SETPOINT_NUDGE_MAX_F))
        # Quantize DOWN to a multiple of STEP (never round up: we must never
        # push the user's setpoint past what the excess warrants).
        nudge = math.floor(nudge / SETPOINT_NUDGE_STEP_F) * SETPOINT_NUDGE_STEP_F

        if heating:
            commanded_heat = baseline_heat + nudge
            commanded_cool = baseline_cool
            if dual and baseline_cool is not None:
                # TRAP 1: raising heat must not violate the min gap with cool.
                commanded_cool = max(baseline_cool,
                                     commanded_heat + SETPOINT_HEATCOOL_MIN_DELTA_F)
        else:
            commanded_cool = baseline_cool - nudge
            commanded_heat = baseline_heat
            if dual and baseline_heat is not None:
                # TRAP 1: lowering cool must not violate the min gap with heat.
                commanded_heat = min(baseline_heat,
                                     commanded_cool - SETPOINT_HEATCOOL_MIN_DELTA_F)
        return commanded_cool, commanded_heat

    # ── Backpressure protection ───────────────────────────────────────────────

    def _coil_temp_for_backpressure(self, hvac_action):
        """Read the suction-line coil temp and apply all feedback gates.

        Returns (coil_temp_f, reason) where coil_temp_f is the suction-line
        temperature in °F, or None if a gate failed (caller falls back to the
        static MAX_CLOSED_RATIO). reason explains which gate held or failed,
        for logging. Also maintains the stuck-sensor detection and the
        emergency latch state.

        Gates (all must hold to return a real temperature):
          1. hvac_action == "cooling" — suction reads warm ambient when the
             compressor is off; using it would falsely trigger aggressive mode.
          2. compressor has run >= COIL_FEEDBACK_MIN_RUNTIME — startup
             transient, suction still settling / carrying residual heat.
          3. sensor state numeric and last_updated within STALE_SEC.
          4. sensor not stuck — some variation over STUCK_WINDOW of runtime.
        """
        if hvac_action != "cooling":
            return None, "not cooling"
        if self._cooling_started_at is None:
            return None, "no cooling-start timestamp"
        runtime = (self.datetime() - self._cooling_started_at).total_seconds()
        if runtime < COIL_FEEDBACK_MIN_RUNTIME:
            return None, f"compressor runtime {runtime:.0f}s < {COIL_FEEDBACK_MIN_RUNTIME}"

        state = self.get_state(COIL_TEMP_SENSOR)
        if state is None or state in ("unavailable", "unknown", ""):
            self._coil_sensor_fail_count += 1
            if self._coil_sensor_fail_count <= 2:
                self.log(f"Coil sensor {COIL_TEMP_SENSOR} unavailable; "
                         f"backpressure falls back to static {MAX_CLOSED_RATIO}")
            return None, "sensor unavailable"
        try:
            temp = float(state)
        except (ValueError, TypeError):
            self._coil_sensor_fail_count += 1
            return None, f"sensor non-numeric: {state!r}"

        # Freshness check
        age = self.get_state(COIL_TEMP_SENSOR, attribute="last_updated")
        if age:
            try:
                age_s = (self.datetime() - self.parse_datetime(age)).total_seconds()
                if age_s > COIL_FEEDBACK_STALE_SEC:
                    self._coil_sensor_fail_count += 1
                    if self._coil_sensor_fail_count <= 2:
                        self.log(f"Coil sensor stale ({age_s:.0f}s old); "
                                 f"backpressure falls back to static {MAX_CLOSED_RATIO}")
                    return None, f"sensor stale {age_s:.0f}s"
            except Exception as e:
                self._coil_sensor_fail_count += 1
                if self._coil_sensor_fail_count <= 2:
                    self.log(f"Coil sensor freshness check failed to parse "
                             f"({e}); don't fail closed on a parse error")

        # Stuck-sensor check: pull recent history; a live suction sensor always
        # moves during compressor runtime. If zero variation over the window,
        # the reading is unreliable (worst case: frozen at 47°F while coil ices).
        # AppDaemon's get_history takes start_time/end_time, not a duration kwarg.
        from datetime import timedelta as _td
        window_start = self.datetime() - _td(seconds=COIL_FEEDBACK_STUCK_WINDOW)
        hist = self.get_history(COIL_TEMP_SENSOR, start_time=window_start)
        if hist and hist[0]:
            vals = []
            for h in hist[0]:
                try:
                    vals.append(float(h["state"]))
                except (ValueError, TypeError):
                    continue
            if vals and (max(vals) - min(vals)) < 0.1:
                self._coil_sensor_fail_count += 1
                if self._coil_sensor_fail_count <= 2:
                    self.log(f"Coil sensor stuck ({len(vals)} samples, zero "
                             f"variation over {COIL_FEEDBACK_STUCK_WINDOW}s); "
                             f"backpressure falls back to static {MAX_CLOSED_RATIO}")
                return None, "sensor stuck"

        self._coil_sensor_fail_count = 0
        return temp, f"runtime {runtime:.0f}s, suction {temp:.1f}F"

    def _coil_ratio_for_temp(self, temp):
        """Map a suction-line temp to a max-closed ratio, with hysteresis.

        Uses the current ratio to decide band transitions: stepping DOWN to a
        more conservative ratio happens at the band's lower edge; stepping UP
        to a more aggressive ratio requires clearing the edge by 2°F (so a
        reading oscillating across a boundary doesn't toggle).
        """
        cur = self._coil_ratio_current
        # Find the highest-aggressive band whose threshold the temp clears,
        # applying 2°F hysteresis when stepping back up from a lower band.
        chosen = MAX_CLOSED_RATIO  # most conservative if nothing matches
        for ratio, edge in COIL_RATIO_BANDS:
            # Hysteresis: if we're currently at a lower (more conservative)
            # ratio than this band, require edge + 2°F to step up to it.
            if cur is not None and ratio > cur:
                need = edge + 2.0
            else:
                need = edge
            if temp >= need:
                chosen = ratio
                break
        return chosen

    def _apply_backpressure_rooms(self, room_positions, hvac_action=None):
        """Ensure we don't close more vents than the coil can safely handle.

        With coil-temperature feedback available (cooling mode, compressor run
        long enough, sensor fresh and not stuck), the max-closed ratio scales
        with suction-line temp — aggressive when the coil is healthy, backing
        off as it approaches freeze. Without feedback, falls back to the static
        MAX_CLOSED_RATIO (the original blind cap).

        Emergency: if suction drops below COIL_EMERGENCY_THRESHOLD, force-open
        closed rooms (latched — requires sustained recovery to release). This
        bypasses mode intent (Cool Upstairs etc.) because freeze protection
        trumps redirection.
        """
        total_vents = len(_get_all_vents())

        # Count vents that would be closed
        closed_count = 0
        for (zone_name, room_name), pos in room_positions.items():
            if pos == 0:
                closed_count += len(ZONES[zone_name]["rooms"][room_name].get("vents", []))

        # Try to get dynamic ratio from coil feedback
        coil_temp, coil_reason = self._coil_temp_for_backpressure(hvac_action)

        # Emergency latch: check first, bypasses everything
        if coil_temp is not None:
            if coil_temp < COIL_EMERGENCY_THRESHOLD:
                if not self._coil_emergency_latched:
                    self._coil_emergency_latched = True
                    self.log(f"*** COIL FREEZE EMERGENCY: suction {coil_temp:.1f}F < "
                             f"{COIL_EMERGENCY_THRESHOLD}F — force-opening closed vents "
                             f"(latched until sustained recovery above "
                             f"{COIL_EMERGENCY_RECOVER}F for {COIL_EMERGENCY_RECOVER_SEC}s) ***")
                self._coil_emergency_since = None  # not recovering yet
            elif self._coil_emergency_latched:
                # Track sustained recovery
                if coil_temp >= COIL_EMERGENCY_RECOVER:
                    if self._coil_emergency_since is None:
                        self._coil_emergency_since = self.datetime()
                    recovered = (self.datetime() - self._coil_emergency_since).total_seconds()
                    if recovered >= COIL_EMERGENCY_RECOVER_SEC:
                        self.log(f"Coil emergency latch released (suction "
                                 f"{coil_temp:.1f}F >= {COIL_EMERGENCY_RECOVER}F sustained "
                                 f"{recovered:.0f}s)")
                        self._coil_emergency_latched = False
                        self._coil_emergency_since = None
                else:
                    self._coil_emergency_since = None  # dipped back down

        if self._coil_emergency_latched:
            # Force-open ALL closed rooms to 50% — freeze protection trumps mode
            opened = 0
            for key, pos in list(room_positions.items()):
                if pos == 0:
                    room_positions[key] = 50
                    n = len(ZONES[key[0]]["rooms"][key[1]].get("vents", []))
                    opened += n
                    self.log(f"  EMERGENCY opened {key[0]}/{key[1]} ({n} vents) -> 50%")
            if opened:
                self.log(f"  Emergency backpressure: opened {opened} vents")
            return room_positions

        # Determine the max-closed ratio to apply
        if coil_temp is not None:
            new_ratio = self._coil_ratio_for_temp(coil_temp)
            new_ratio = min(new_ratio, MAX_CLOSED_RATIO_HARD_CEILING)
            # Dwell gate: don't change the ratio more often than DWELL_SEC
            now = self.datetime()
            if (self._coil_ratio_current is not None
                    and self._coil_ratio_changed_at is not None
                    and abs(new_ratio - self._coil_ratio_current) > 0.001
                    and (now - self._coil_ratio_changed_at).total_seconds() < COIL_FEEDBACK_DWELL_SEC):
                # Within dwell window — hold the current ratio
                new_ratio = self._coil_ratio_current
            if self._coil_ratio_current != new_ratio:
                if self._coil_ratio_current is not None:
                    self.log(f"Coil backpressure ratio: {self._coil_ratio_current:.0%} -> "
                             f"{new_ratio:.0%} (suction {coil_temp:.1f}F, {coil_reason})")
                self._coil_ratio_current = new_ratio
                self._coil_ratio_changed_at = now
            max_closed = int(total_vents * new_ratio)
            bp_label = f"dynamic {new_ratio:.0%} (suction {coil_temp:.1f}F)"
        else:
            # No feedback — static fallback
            max_closed = int(total_vents * MAX_CLOSED_RATIO)
            new_ratio = MAX_CLOSED_RATIO
            bp_label = f"static {MAX_CLOSED_RATIO:.0%} ({coil_reason})"

        if closed_count <= max_closed:
            return room_positions

        self.log(f"Backpressure: {closed_count} vents would close, "
                 f"max allowed {max_closed} ({bp_label}). Opening rooms to 50%.")

        # Open rooms with fewest vents first until under limit
        closed_rooms = [
            (key, len(ZONES[key[0]]["rooms"][key[1]].get("vents", [])))
            for key, pos in room_positions.items() if pos == 0
        ]
        closed_rooms.sort(key=lambda x: x[1])

        for key, count in closed_rooms:
            room_positions[key] = 50
            closed_count -= count
            self.log(f"  Opened {key[0]}/{key[1]} ({count} vents) to 50% for backpressure")
            if closed_count <= max_closed:
                break

        return room_positions

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_thermostat_state(self):
        """Read ecobee thermostat state, current action, and setpoints.

        Returns (hvac_mode, hvac_action, target_cool, target_heat).
        hvac_action is what the system is actually doing right now:
          'cooling', 'heating', 'idle', 'fan', 'off'
        """
        state = self.get_state(THERMOSTAT, attribute="all")
        if not state:
            return "off", "off", None, None

        attrs = state.get("attributes", {})
        hvac_mode = state.get("state", "off")
        hvac_action = attrs.get("hvac_action", "idle")

        target_cool = attrs.get("target_temp_high")
        target_heat = attrs.get("target_temp_low")

        # Single setpoint mode
        if target_cool is None and target_heat is None:
            single = attrs.get("temperature")
            if single:
                if hvac_mode == "cool":
                    target_cool = single
                elif hvac_mode == "heat":
                    target_heat = single
                else:
                    target_cool = single
                    target_heat = single

        return hvac_mode, hvac_action, target_cool, target_heat

    def _read_temp(self, entity):
        """Read a temperature sensor, returning float or None."""
        val = self.get_state(entity)
        if val in (None, "unknown", "unavailable"):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _set_vent(self, entity, position):
        """Set a vent to a position, respecting manual holds."""

        # Check manual hold
        if entity in self._manual_holds:
            if datetime.now() < self._manual_holds[entity]:
                return  # Still in manual hold, don't touch
            else:
                del self._manual_holds[entity]  # Hold expired

        # Check if vent is available
        state = self.get_state(entity)
        if state == "unavailable":
            return

        # Don't send redundant commands
        current = self.get_state(entity, attribute="current_tilt_position")
        if current == position:
            return

        self.log(f"Setting {entity} -> {position}%")
        # FIRE-AND-FORGET via callback=. 2026-08-08 incident: this app runs
        # on a single pinned AppDaemon worker thread (the default for a
        # pinned app), shared by control_loop/on_occupancy_change/heartbeat.
        # By default call_service() BLOCKS that thread waiting on HA's
        # response. Two hass_timeout warnings earlier that evening fired and
        # recovered fine, but a later set_cover_tilt_position call went
        # silent — no exception, no further log lines — and never returned,
        # which meant every future scheduled callback on this app queued up
        # behind it forever (the control loop never ran again, the
        # heartbeat sensor froze, vents held whatever position they had for
        # ~4.5h until a manual add-on restart un-wedged the thread).
        # Per AppDaemon's own docs, passing callback= is "the recommended
        # method for calling services which might take a long time to
        # complete" — it returns immediately instead of blocking, so a
        # single hung/orphaned response can no longer freeze the whole app.
        # hass_timeout is kept too as defense-in-depth even though it's not
        # the primary fix (it didn't stop the original hang).
        self.call_service(
            "cover/set_cover_tilt_position",
            entity_id=entity,
            tilt_position=position,
            hass_timeout=8,
            callback=self._service_call_done,
        )
        self._last_positions[entity] = position

    def _service_call_done(self, *args, **kwargs):
        """No-op completion callback — see _set_vent for why fire-and-forget
        matters. Accepts *args/**kwargs defensively since we don't rely on
        AppDaemon's exact ServiceCallback signature; we only care that this
        call doesn't block. Left as a hook for future diagnostics (e.g. log
        non-OK results) without reintroducing a blocking wait.
        """
        pass
