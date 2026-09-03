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
from collections import namedtuple

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
                # donor_only: the room houses cats, not people. The animals are
                # a real, continuous sensible heat load, so the room reads warm
                # and the base scoring interprets that as cooling demand — but
                # there is no human comfort requirement here, so it must never
                # win airflow away from a room people actually occupy. Distinct
                # rationale from the other donor_only rooms (Hallway/Main
                # Bedroom = pass-through/typically-empty, Laundry = transient
                # 10-min occupancy blips): this room is genuinely, permanently
                # occupied and genuinely warm, it just isn't occupied by anyone
                # whose comfort we're optimizing for. It can still be a DONOR
                # (throttled to feed a hotter human-occupied room) and its own
                # vents still open/close normally on its own temp — it simply
                # can never be a BENEFICIARY. Added 2026-09-02 after the
                # controller was observed pinning it to 100% ("hot override
                # (+4.8) -> 100% regardless of occupancy") while Game Room sat
                # +11.2F over with "no donor rooms" available.
                "donor_only": True,
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
                # donor_only: a guest bathroom is transient-use space, not a
                # room anyone is settled in — same reasoning as Hallway and
                # Laundry Room. max_vent_pct only CAPS how far it opens; it
                # does not stop the room competing for airflow in the priority
                # pass. Without this, the controller logs "Priority Guest
                # Bathroom (75.0F, off+3.0) [cool,ESCALATED] struggling but no
                # donor rooms" and treats a room with nobody in it as a
                # beneficiary while Game Room sits +11F over with no donors
                # available. It can still be a DONOR and its own vent still
                # follows normal temp logic (including closing to 0% when
                # satisfied — max_vent_pct is a ceiling, not a floor).
                # Added 2026-09-02.
                "donor_only": True,
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

# Cloud-truth setpoint sensors exposed by the ecobee_enhanced integration.
# They mirror the ecobee runtime's authoritative desiredCool/desiredHeat — the
# LIVE setpoints the cloud actually holds, updated on the coordinator's poll
# AND immediately after any write (the integration force-refreshes). The
# setpoint-nudge MUST read its ownership readback and baseline from THESE, NOT
# from the homekit_controller mirror (THERMOSTAT / climate.ecobee_thermostat),
# which does NOT reflect a cloud-side hold and caused the live relinquish /
# re-engage churn loop (it kept reporting 66/60 while the real hold was
# cool 63 / heat 57). These are whole-degree °F strings, e.g. "63.0".
SETPOINT_TRUTH_COOL = "sensor.ecobee_edgewater_road_desired_cool"
SETPOINT_TRUTH_HEAT = "sensor.ecobee_edgewater_road_desired_heat"

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

# DOWNSTAIRS OCCUPIED COOLING LADDER (2026-09-02 redesign, user requirement):
# "downstairs vents should be fully closed until an occupied room drifts
# above 1F over setpoint, then 50% until 2F over, then 100%" — explicit
# three-tier ladder measured against RAW distance-from-setpoint (temp -
# target_cool), NOT the occ_bonus-inflated `need` the rest of this function
# uses for scoring. Bug this replaces: `need` adds a flat +1.0F occupied
# bonus BEFORE comparing to OCC_DEADBAND_DOWNSTAIRS (1.5F), so a room only
# 0.5F raw over setpoint was already scoring 1.5F and opening — silently
# halving the user's intended 1.0F margin. This ladder is self-contained
# (both thresholds enforced directly against raw, not derived from
# OCCUPANCY_OVERRIDE_OVER/occ_bonus) so it stays correct even if those
# other constants are retuned later — see _auto_calculate's downstairs/
# basement occupied-cooling branch for where this is applied. Heating and
# upstairs are UNCHANGED (upstairs keeps its original tight OCC_DEADBAND_
# UPSTAIRS behavior; downstairs/basement heating keeps the flat DEADBAND
# ladder, "not the focus of this tuning" per the original comment above).
DOWNSTAIRS_OCC_OPEN_THRESHOLD_F = 1.0  # raw °F over setpoint: closed -> 50%
DOWNSTAIRS_OCC_FULL_THRESHOLD_F = 2.0  # raw °F over setpoint: 50% -> 100%

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
# 2026-09-02: raised 8 -> 12. There are 13 rooms total, so 12 == "every other
# room", which effectively RETIRES this as a limiter and leaves the dynamic
# backpressure pass (coil suction-temp feedback, MAX_CLOSED_RATIO 40-80%) as
# the single authority on how much of the house may be closed at once. That
# is the measured safety net; this was an arbitrary count sitting in front of
# it. History: 4 -> 8 when dynamic backpressure landed, now -> 12 for the same
# reason, one step further.
# Worth being explicit about what this does NOT fix: on 2026-09-02 with Game
# Room +11F over, only 5-6 rooms QUALIFIED as donors at all (a donor must be
# PRIORITY_DONOR_COOLER_BY=1.5F cooler than the beneficiary, and on a losing
# whole-house day almost nothing is). The cap was never the binding
# constraint that night — eligibility was. Raising it only matters on days
# when 9+ rooms are genuinely comfortable and one room is genuinely losing.
PRIORITY_MAX_DONORS = 12
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

# ── Saturation: when escalation has been PROVEN not to work ──────────────────
# (2026-09-02, driven by a physical measurement.)
#
# The delivery-handicap detector above identifies a room that is occupied,
# off-target, WIDE OPEN, receiving genuinely cold supply air, and STILL not
# approaching setpoint. Until now the response was to ESCALATE: throttle that
# room's donors from 50% all the way to 0% to shove even more CFM at it.
#
# A bag test on Game Room (13-gal bag, 2.0 s/register, 3 registers) measured
# 156 CFM total — while all 3 of its vents were at 100% AND seven other rooms
# were already throttled to 0% feeding it. That is the system at maximum
# effort. Holding 72F in that room needs ~250 CFM. The duct is the ceiling,
# not the damper positions and not the room's share of the house.
#
# So for a proven-saturated room, escalation is actively COUNTERPRODUCTIVE:
#   - the blower is a 5-speed CONSTANT-TORQUE ECM, not constant-CFM, so every
#     additional closed damper raises static and LOWERS total house CFM
#   - the saturated room still receives only its duct's ~156 CFM regardless
#   - the airflow removed from donor rooms is therefore purely wasted, and
#     worse, it's taken from rooms that WOULD have responded to it
#
# Rather than hard-flipping on the penalty threshold (which would oscillate,
# since Game Room's penalty hovers right at ~1.68 vs the 1.5 threshold), this
# is a state machine that runs the escalation experiment FIRST and only
# inverts after watching it fail. The detector cannot tell "duct-limited"
# apart from "damper stuck / door closed / transient load spike" on a single
# sample — escalating for a few cycles is the correct diagnostic probe.
#
# Entry: SATURATION_ENTER_CYCLES consecutive cycles already escalated, still
#        below DELIVERY_STUCK_RATE. Exit needs a SUSTAINED responsive rate
#        (separate, higher bar than entry — deliberate hysteresis), because
#        saturation is LOAD-DEPENDENT, not permanent: Game Room does reach
#        72.7F overnight, and a flag that never cleared would sabotage the
#        overnight pre-cool window.
SATURATION_ENTER_CYCLES = 3      # ~6 min at the 120s loop: probe, then judge
SATURATION_EXIT_CYCLES = 2       # sustained recovery before un-latching
SATURATION_EXIT_RATE = 0.08      # °F/min approach that counts as "responding"
                                 # (higher than DELIVERY_STUCK_RATE=0.05 on
                                 # purpose — the exit bar must clear the entry
                                 # bar or the flag chatters at the boundary)
# A saturated room keeps its OWN vents at 100% (it should still get every bit
# of air its duct can carry) but its donor recruitment is capped to this many
# rooms, and those donors are throttled to 50% rather than 0%. Not zero: a
# small amount of concentration is still worth having, and a hard 0 would make
# the inversion untestable against the "escalation helps a bit" hypothesis.
SATURATION_MAX_DONORS = 2

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
#
# DISABLED 2026-09-02 (SAME DAY, RE-ENABLED LATER) — root-cause finding (see
# smart-vent-controller skill, "Setpoint-nudge on an AVERAGED-sensor
# thermostat drags the WHOLE HOUSE colder" + independent Opus review same
# day): climate.ecobee_thermostat controls to the AVERAGE of all 14 remote
# sensors, not to the worst room. Dropping the cool setpoint to force Game
# Room's compressor to escalate does NOT "stage harder for a fixed target" —
# it moves the whole-house TARGET colder, so every well-behaved room (Living
# Room, Kitchen) gets dragged well below ITS OWN comfortable point to pull
# the house average down to chase one chronically-underserved room. That is
# what produced the "freezing Living Room/Kitchen" complaint on 2026-09-02
# (nudge engaged 07:44, deepened to cool=70F by 07:55, user manually
# corrected back to 72F by 08:13).
#
# RE-ENABLED same day (2026-09-02, afternoon) after two structural fixes
# closed the actual failure mode (see commits 745414b/3ef9b6e + the RESOLVED
# section of the skill):
#   1. SETPOINT_NUDGE_GAIN/MAX_F collapsed to a fixed, hard-capped 1.0F
#      nudge — it can NEVER again drag the house 3F+ colder no matter how
#      hot Game Room gets. It can still move the AVERAGE, but only by 1F.
#   2. SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN (2h) makes any human correction
#      final for 2 hours — it can never fight the user again after they
#      touch the thermostat.
# Live justification for re-enabling, verified from real data before
# flipping this: Game Room at 76.5F, all 3 vents open 100%, duct temps
# 54-56F (cold air genuinely reaching it — NOT a duct/airflow capacity
# problem), compressor stuck at stage 1 all afternoon because the house
# average reads 72-73F against the 72F setpoint. Vent redistribution had
# already done everything it can (5 donor rooms throttled to 0%, escalated
# tier) — the remaining lever is compressor staging, decided off the
# average, the one thing vents can't touch. Exactly the scenario this
# mechanism exists for, now with both required guardrails in place.
SETPOINT_NUDGE_ENABLED    = True  # master switch — see note above (re-enabled 2026-09-02)
SETPOINT_NUDGE_ENGAGE_F   = 1.5   # worst_excess at/above this engages a nudge
SETPOINT_NUDGE_RELEASE_F  = 0.5   # worst_excess at/below this releases it (hysteresis band; MUST be < ENGAGE)
# GAIN/MAX_F chosen to guarantee a SINGLE, CONSTANT-MAGNITUDE nudge of exactly
# MAX_F degrees whenever the mechanism engages at all (2026-09-02 redesign
# requirement, tightened same day): nudge_amount = floor(clamp(worst_excess *
# GAIN, 0, MAX_F) / STEP_F) * STEP_F. As long as GAIN * ENGAGE_F >= MAX_F, the
# clamp ALWAYS saturates the instant a nudge is allowed to engage at all (the
# minimum possible worst_excess to engage is ENGAGE_F itself) — so the nudge
# can never be a smaller, in-between value; it is either 0 (not engaged) or
# exactly MAX_F. This directly encodes the user's explicit requirement: "if
# it's set to 72, I don't want the first floor cooling down to 70 to get the
# upstairs down to 73" — the ORIGINAL baseline (see baseline_cool/
# baseline_heat, captured from cloud truth at engage time = whatever the
# human currently has it at, manually or via schedule) is the accepted
# reference point, and the nudge may move AT MOST MAX_F degrees past it,
# period, never partially and never more. Because MAX_F is the saturated
# value from the very first engage, "deepening" (re-nudging further off the
# same baseline after dwell) can never produce a MORE aggressive value than
# what's already commanded — the deepen branch's own "only write if strictly
# more aggressive" guard makes it a permanent no-op once engaged, so this is
# always a single-shot nudge, never a ratchet.
#
# MAX_F raised 1.0 -> 2.0 (2026-09-02, same day as the fixed-magnitude
# redesign above): this house's stage-2 cooling differential is a MANUAL-ONLY
# ecobee setting (not API-readable — see the ecobee-api-reference skill),
# confirmed at 2.0F, and the compressor stages up only once the AVERAGED
# controlling temp EXCEEDS setpoint+2.0F, not merely reaches it. Live data
# the day this was raised: house average sits ~1F over the user's real
# baseline setpoint even before any nudge, so a 1.0F nudge only pushed the
# gap to EXACTLY 2.0F — the boundary, not past it — and stage 2 never fired
# even after 10+ minutes at that gap. GAIN raised 1.0 -> 2.0 alongside MAX_F
# so saturation is still guaranteed (1.5 engage * 2.0 gain = 3.0 >= 2.0 cap)
# — this is a magnitude change only, the single-shot/no-ratchet guarantee
# above is unaffected. Vent scoring is UNCHANGED by this: _active_nudge_
# baseline (see below) always scores every room against the pre-nudge
# baseline setpoint, never the live nudged one, so deepening the nudge's
# magnitude has zero effect on how Living Room/Kitchen are judged for
# comfort — only the compressor's target moves, never the vents' target.
SETPOINT_NUDGE_GAIN       = 2.0   # degrees of setpoint nudge per degree of worst_excess
SETPOINT_NUDGE_MAX_F      = 2.0   # hard cap on how far we may ever move the user's setpoint (2026-09-02: 3.0 -> 1.0 -> 2.0, see note above)
# ecobee stores/reports setpoints as WHOLE DEGREES only. The baseline captured at
# engage is already a whole degree, so quantizing nudge_amount to a whole-degree
# multiple makes every COMMANDED setpoint land exactly on a value the thermostat
# can represent. That is load-bearing: a 0.5F command (e.g. 71.5) reads back as
# the nearest whole degree (71), a 0.5F mismatch that trips the readback-match
# tolerance (0.2F), which the app misreads as "the user changed the setpoint",
# adopts its OWN nudge residue as the new baseline, and nudges AGAIN — ratcheting
# the house 73->71->69->66. Whole-degree command == whole-degree readback, so
# spurious ownership loss is impossible. ACCEPTED consequence: the minimum
# effective nudge is now 1.0F instead of 0.5F (a 0.5F nudge was physically
# unrepresentable and could never have worked). preserve the quantize-DOWN
# (floor) behavior and the 0..SETPOINT_NUDGE_MAX_F clamp below.
SETPOINT_NUDGE_STEP_F     = 1.0   # ecobee setpoint granularity (whole degrees); quantize to this
SETPOINT_NUDGE_DWELL_SEC  = 600   # min seconds between setpoint writes (>= compressor min-ON 10min; prevents fighting the ecobee's own staging)
SETPOINT_NUDGE_CONFIRM_SEC= 420   # readback mismatch must persist this long before it's believed (ecobee cloud poll floor is 3 min)
SETPOINT_NUDGE_TOLERANCE_F= 0.2   # readback match tolerance
SETPOINT_HEATCOOL_MIN_DELTA_F = 6.0  # ecobee heatCoolMinDelta, see TRAP 1 below
# HUMAN-OVERRIDE COOLDOWN (2026-09-02): once a live-readback mismatch confirms
# the USER changed the setpoint out from under an active nudge, the mechanism
# must NOT immediately turn around and re-engage a fresh nudge next cycle if
# the offending room is still hot -- that is functionally "fighting" the human
# the instant they act, just with an extra ~2-4 minute detection delay instead
# of an instant pop. User's explicit requirement (2026-09-02): "anything done
# by a human on the thermostat is THE be all end all" -- a detected override
# must make the mechanism back off for a real window, not retry on the next
# 120s cycle. This is a HARD requirement, not a tunable nicety: it applies
# regardless of worst_excess, escalation, or how hot the room still is.
SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN = 120  # 2h: no new engagement after a detected human override

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

# ── Midday predictive pre-cool (daytime priority-margin mechanism) ───────────
# Sun-facing rooms start each afternoon already behind because the morning is
# spent NOT favoring them. During the pre-sun window, while cooling is happening
# anyway, bias ANY occupied room that's drifting up so it banks headroom before
# the solar load arrives. Lower activation margin (react earlier) during these
# local hours, applied house-wide.
#
# NOTE: renamed from the old bare names (2026-09-02, pure rename, no
# behavior change) to disambiguate from the unrelated OVERNIGHT pre-cool
# feature (PRECOOL_WINDOW_*, PRECOOL_TARGETS, etc. below) which merely shares
# the word "precool" but is a completely separate mechanism.
MIDDAY_PRECOOL_HOURS = range(10, 14)   # 10:00–13:59 local time
MIDDAY_PRECOOL_MARGIN = 0.5            # engage priority pass when only this far over

# ── Overnight pre-cool (PHASE 1: foundation layer) ────────────────────────────
# Distinct from the midday priority-margin mechanism above -- shares the word
# "precool", nothing else. Game Room has a documented ~40% duct deficit that
# software cannot fix
# (measured: ~156 CFM max at 100% open + 7 donors, needs ~250 CFM to hold 72F
# -- see test_saturation_and_donor_budget.py). Overnight pre-cool's job is to
# SHIFT/SHAVE the afternoon peak by cooling Game Room and Guest Bedroom 1 down
# toward a floor overnight (when demand is low and there's spare capacity),
# not to eliminate the deficit.
#
# Window: 01:00 inclusive - 06:30 exclusive local time. Minutes-since-midnight
# comparison (NOT hour-only `in range()`) because the end boundary falls on a
# half hour.
PRECOOL_WINDOW_START_HOUR = 1
PRECOOL_WINDOW_START_MIN = 0
PRECOOL_WINDOW_END_HOUR = 6
PRECOOL_WINDOW_END_MIN = 30

# The ONLY two pre-cool target rooms and their floor temps (°F). NOT
# house-wide, NOT "all upstairs rooms" -- exactly these two, by design.
# Occupancy does NOT gate these targets (a sleeping person may not trip a
# PIR) -- the floors themselves ARE the occupant-comfort protection.
PRECOOL_TARGETS = {
    ("upstairs", "Game Room"): 68.0,
    ("upstairs", "Guest Bedroom 1"): 69.0,
}

# Hard safety floor: ANY occupied room (house-wide, not just the two
# targets) reading at or below this aborts pre-cool for the cycle.
PRECOOL_ABORT_OCCUPIED_F = 67.0

# Humidity guard. Dewpoint is the PRIMARY, physically-correct gate: at a
# fixed real dewpoint, RH mechanically RISES as sensible temp drops from
# cooling alone, so an RH ceiling alone would trip on physics, not on an
# actual moisture problem. RH is only a BACKSTOP against a frozen/broken
# dewpoint sensor.
PRECOOL_DEWPOINT_MAX_F = 58.0
PRECOOL_RH_MAX_PCT = 65.0
PRECOOL_DEWPOINT_ENTITY = "sensor.indoor_dew_point"
PRECOOL_HUMIDITY_ENTITY = "sensor.indoor_humidity_live"

# Main Bedroom -- and every other non-target room -- is intentionally NOT
# configured here. Earlier versions of this feature forced Main Bedroom to a
# fixed "donor throttle" position whenever pre-cool was active, regardless of
# Main Bedroom's own measured comfort need. That was a bug: it stomped the
# base need-based ladder's already-correct value computed earlier in the
# pipeline (_auto_calculate, refined by _apply_priority_rooms /
# _apply_fan_assist) with an arbitrary hardcoded number. Per the user's
# explicit correction (2026-09-03): "a donor's vent position should reflect
# the donor's OWN comfort need, not a value forced by the beneficiary
# passes." _apply_precool_vents below now touches ONLY the two
# PRECOOL_TARGETS rooms -- Main Bedroom's position during the pre-cool window
# is purely a function of its own measured need, exactly like every other
# non-target room, exactly as it was before this feature existed. (The
# PRE-EXISTING, separate donor_only mechanism in ZONES -- consumed by
# _apply_priority_rooms, unrelated to and untouched by this feature -- may
# still independently throttle Main Bedroom to help a DIFFERENT struggling
# room; that is orthogonal and not what this comment is about.)

# Observability sensor -- mirrors DELIVERY_PENALTY_ENTITY's publishing shape
# (numeric state + per-room attributes dict). Published every cycle,
# including outside the window, so last night's result stays visible until
# the next window engages.
PRECOOL_ENTITY = "sensor.smart_vent_precool"

# ── Overnight pre-cool (PHASE 2: setpoint-nudge demand source) ────────────────
# Pre-cool's release threshold, measured on ITS OWN axis: pre-cool demand =
# (room temp - its PRE-COOL FLOOR), NOT the comfort axis's (off_target -
# _room_margin). Defined as its own constant, deliberately NOT an alias of
# SETPOINT_NUDGE_RELEASE_F, even though both currently read 0.5:
#   - they measure DIFFERENT quantities against DIFFERENT references (comfort
#     setpoint + activation margin vs. the fixed overnight floor), so a future
#     retune of one must never silently drag the other with it, and
#   - the magnitude 0.5 is chosen on pre-cool's own merits: the floors are
#     targets to converge on, not hard limits, so holding the compressor
#     hostage for the last half degree overnight buys nothing measurable while
#     risking an all-night hold. Within 0.5F of the floor, pre-cool is done.
# Pre-cool's ENGAGE bar is deliberately NOT a separate constant: engagement
# runs through the EXISTING SETPOINT_NUDGE_ENGAGE_F gate fed by the combined
# (max) demand -- one engage threshold, one depth computation, per the
# Kitchen/priority-pass two-layers-disagreeing bug class.
PRECOOL_NUDGE_RELEASE_F = 0.5

# Result of _precool_gate(), computed once per cycle and consumed by both the
# vent pass (_apply_precool_vents) and the setpoint-nudge integration
# (_precool_demand, consumed by _apply_setpoint_nudge). Keep ONE gate function
# so the two consumers never disagree about a threshold.
# `suppressed` is the PHASE 2 human-override veto: True while a confirmed human
# setpoint override has vetoed pre-cool for the REST of the current window-
# night. Defaulted so any caller constructing a gate positionally/by-keyword
# without it (offline harnesses) keeps working unchanged.
PrecoolGate = namedtuple(
    "PrecoolGate",
    ["active", "window_active", "cold_abort", "humidity_ok", "reason",
     "suppressed"],
    defaults=[False],
)


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

        # SATURATION state (2026-09-02). A room is "saturated" once we have
        # PROVEN, by running the escalation experiment and watching it fail,
        # that it is physically incapable of absorbing more airflow — its duct
        # is the limit, not its vent position or its share of the house.
        # _saturation_streak[key] counts consecutive cycles the room has sat at
        # maximum effort (wide open, well-supplied, donors escalated) while
        # STILL not approaching setpoint. _saturated_rooms is the latched set.
        # See the constants block for the entry/exit thresholds and why this
        # inverts the room's treatment instead of escalating harder.
        self._saturation_streak = {}
        self._saturated_rooms = set()
        self._saturation_recover = {}

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
        # HUMAN-OVERRIDE COOLDOWN (2026-09-02): timestamp of the most recent
        # confirmed human setpoint change (detected via the readback-mismatch
        # ->confirm path). None means no override on record / cooldown expired.
        # Set at the moment of detection, persisted immediately (survives an
        # app restart -- see _persist_nudge_state/_restore_nudge_ownership),
        # and gates the not-owned engage branch in _apply_setpoint_nudge:
        # no new nudge may engage while now - this < OVERRIDE_COOLDOWN_MIN,
        # regardless of worst_excess. This is what makes a detected override
        # STOP the mechanism instead of merely delaying the next re-engage by
        # one CONFIRM_SEC window.
        self._sp_override_cooldown_until = None
        # One-shot log guard for a missing/unavailable cloud-truth setpoint
        # sensor (see _apply_setpoint_nudge): True after we've logged the
        # "cloud-truth unavailable" line once, so we don't spam every 120s cycle.
        self._sp_truth_unavailable_logged = False

        # OVERNIGHT PRE-COOL state (PHASE 1 foundation, 2026-09-02). See the
        # PRECOOL_* constants block. _precool_min_temps[room_key] = the
        # minimum temp that target room has reached so far during the
        # CURRENT window-night. _precool_window_id identifies which window
        # the tracker belongs to (the date of that window's 01:00 start, as
        # an ISO string) so a new night resets the tracker instead of
        # carrying over the prior night's minimum. One-shot log guards for
        # the humidity gate mirror _sp_truth_unavailable_logged above: log a
        # state CHANGE once, not every cycle.
        self._precool_min_temps = {}
        self._precool_window_id = None
        self._precool_dewpoint_unavailable_logged = False
        self._precool_humidity_blocked_logged = False
        # PHASE 2 human-override veto. Holds the window-night id (same
        # _precool_window_id_for string) of a window in which a CONFIRMED human
        # setpoint override was detected. While it equals the CURRENT window's
        # id, _precool_gate() stays inactive -- for the REST of that night, not
        # merely the 2h SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN: once a human has
        # vetoed the mechanism overnight, waiting out a timer and quietly
        # resuming the same night is exactly the "fighting the human" behavior
        # the cooldown exists to prevent. Persisted with the nudge state so a
        # restart mid-window cannot resurrect a vetoed pre-cool. A stale id
        # from a previous night is inert by construction (it can never equal
        # tonight's id), so it needs no expiry sweep.
        self._precool_suppressed_window_id = None

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

        # Overnight pre-cool (PHASE 1 foundation): shifts Game Room / Guest
        # Bedroom 1 toward their floors during the 01:00-06:30 window,
        # throttling Main Bedroom as donor. Purely a vent-position pass, like
        # fan-assist above -- runs before the setpoint nudge and before
        # backpressure (which remains the final safety net). No-op outside
        # the window / when the gate is inactive. The gate is also published
        # every cycle so the last window's result stays observable.
        precool_gate = self._precool_gate()
        room_positions = self._apply_precool_vents(room_positions, precool_gate)
        self._publish_precool_sensor(precool_gate)

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
        #
        # PHASE 2: the SAME precool_gate computed above is passed in as the
        # nudge's SECOND DEMAND SOURCE. It is deliberately the identical gate
        # object the vent pass just consumed -- computed once per cycle, never
        # re-evaluated -- so the two passes can never disagree about whether
        # pre-cool is running this cycle. The nudge remains the ONLY setpoint
        # writer in this app; pre-cool contributes a demand value, never a
        # write.
        self._apply_setpoint_nudge(hvac_mode, hvac_action, target_cool,
                                   target_heat, mode,
                                   precool_gate=precool_gate)

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
                # Defensive init: only ever consumed under `if is_cooling and
                # zone_name in ("downstairs", "basement")` below, where
                # is_cooling guarantees it was actually set — but initialize
                # unconditionally so static analysis (and any future
                # reordering) can't accidentally read it unbound.
                raw_off_setpoint = None

                if is_cooling:
                    if target_cool is None:
                        room_positions[key] = 50
                        continue
                    need = temp - target_cool
                    # RAW (pre-bonus) distance-over-setpoint, captured BEFORE
                    # any heat-rise/occ_bonus adjustment below. Used by the
                    # downstairs/basement occupied-cooling ladder (see
                    # DOWNSTAIRS_OCC_OPEN_THRESHOLD_F/FULL_THRESHOLD_F) so
                    # that ladder's 1.0F/2.0F thresholds are measured against
                    # the room's ACTUAL temperature gap, never inflated by
                    # the +1.0F occupied bonus meant for the rest of this
                    # function's scoring (that inflation was the bug: it
                    # silently halved the user's intended 1.0F margin).
                    raw_off_setpoint = need
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
                    # DOWNSTAIRS/BASEMENT COOLING: explicit 3-tier ladder
                    # against RAW distance-over-setpoint (2026-09-02 user
                    # requirement — see DOWNSTAIRS_OCC_OPEN_THRESHOLD_F/
                    # FULL_THRESHOLD_F comment): closed until >1.0F raw,
                    # 50% from 1.0F to 2.0F raw, 100% past 2.0F raw. This
                    # replaces the occ_bonus-inflated `need` comparison for
                    # this specific branch only — upstairs and all heating
                    # are UNCHANGED below (fall through to the original
                    # occ_deadband logic, which still uses `need`).
                    if is_cooling and zone_name in ("downstairs", "basement"):
                        if raw_off_setpoint > DOWNSTAIRS_OCC_FULL_THRESHOLD_F:
                            pos = 100
                            reason = (f"needs airflow, occupied, raw "
                                      f"{raw_off_setpoint:+.1f} > "
                                      f"{DOWNSTAIRS_OCC_FULL_THRESHOLD_F:+.1f} "
                                      f"— 100%")
                        elif raw_off_setpoint > DOWNSTAIRS_OCC_OPEN_THRESHOLD_F:
                            pos = 50
                            reason = (f"needs airflow, occupied, raw "
                                      f"{raw_off_setpoint:+.1f} > "
                                      f"{DOWNSTAIRS_OCC_OPEN_THRESHOLD_F:+.1f} "
                                      f"— 50%")
                        else:
                            # At/under the 1.0F raw open threshold: fully
                            # closed, no hysteresis/trickle band. The user
                            # was explicit this should be a hard binary step
                            # at 1.0F, not the softer near-setpoint/hysteresis
                            # treatment the rest of this function uses.
                            pos = 0
                            reason = (f"satisfied, occupied, raw "
                                      f"{raw_off_setpoint:+.1f} <= "
                                      f"{DOWNSTAIRS_OCC_OPEN_THRESHOLD_F:+.1f} "
                                      f"— 0%")
                    # Per-floor OCCUPIED deadband: downstairs tolerates more
                    # real deviation before locking to 100% (and becoming
                    # donor-immune) than upstairs does — see OCC_DEADBAND_*
                    # comment above. Numerically equal to DEADBAND for
                    # upstairs, so upstairs behavior is unchanged.
                    elif need > occ_deadband:
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
                # Hoisted out of the `prev is not None` branch below so the
                # saturation state machine can read it after this block. None
                # means "no usable rate sample this cycle" (first sample after
                # start/idle, or the gap between samples was out of range) —
                # distinct from 0.0, which is a real measured non-response.
                rate_for_saturation = None
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
                        rate_for_saturation = rate
                        if (occupied and off > DEADBAND and wide_open
                                and well_supplied and rate < DELIVERY_STUCK_RATE):
                            stuck = True
                            contribution = min(off, DELIVERY_PENALTY_MAX)

                prevp = self._delivery_penalty.get(key, 0.0)
                self._delivery_penalty[key] = (
                    DELIVERY_PENALTY_EMA * contribution
                    + (1 - DELIVERY_PENALTY_EMA) * prevp
                )

                # ── Saturation state machine (2026-09-02) ───────────────────
                # "stuck" above already means: occupied, off-target, WIDE OPEN,
                # well-supplied, and not approaching setpoint. The remaining
                # question is whether escalation can still rescue it, or whether
                # the duct itself is the ceiling.
                #
                # We only count a cycle toward saturation once the room is
                # ALREADY being escalated (penalty past DELIVERY_ESCALATE_PENALTY
                # means the priority pass is throttling its donors to 0%). That
                # ordering matters: it makes the streak a record of "maximum
                # effort was applied and it still didn't move", i.e. the
                # escalation experiment ran and failed — not merely "this room
                # is hot". A room that is stuck but NOT yet escalated is still
                # in the diagnostic-probe phase and must not latch.
                already_escalated = (
                    self._delivery_penalty[key] >= DELIVERY_ESCALATE_PENALTY)
                if stuck and already_escalated:
                    self._saturation_streak[key] = (
                        self._saturation_streak.get(key, 0) + 1)
                    if (self._saturation_streak[key] >= SATURATION_ENTER_CYCLES
                            and key not in self._saturated_rooms):
                        self._saturated_rooms.add(key)
                        self.log(
                            f"SATURATED: {room_name} — {SATURATION_ENTER_CYCLES}"
                            f" consecutive cycles wide open, well-supplied, "
                            f"donors already escalated, still <"
                            f"{DELIVERY_STUCK_RATE}F/min. Escalation has been "
                            f"proven ineffective; capping its donor recruitment "
                            f"at {SATURATION_MAX_DONORS} (50%, not 0%) so the "
                            f"airflow goes to rooms that can still use it.")
                elif rate_for_saturation is not None and rate_for_saturation >= SATURATION_EXIT_RATE:
                    # Responding again. Saturation is LOAD-dependent (Game Room
                    # does recover overnight), so this must be able to clear.
                    # Require a sustained recovery, and use a higher rate bar
                    # than the entry test so the flag can't chatter.
                    self._saturation_recover[key] = (
                        self._saturation_recover.get(key, 0) + 1)
                    if self._saturation_recover[key] >= SATURATION_EXIT_CYCLES:
                        self._saturation_streak[key] = 0
                        self._saturation_recover[key] = 0
                        if key in self._saturated_rooms:
                            self._saturated_rooms.discard(key)
                            self.log(
                                f"SATURATION CLEARED: {room_name} approaching "
                                f"setpoint at >= {SATURATION_EXIT_RATE}F/min for "
                                f"{SATURATION_EXIT_CYCLES} cycles — it can absorb "
                                f"airflow again, restoring normal donor recruitment.")
                else:
                    # Neither clearly stuck-at-max-effort nor clearly recovering
                    # (e.g. vents just moved, or the room is idle). Decay the
                    # streak rather than resetting it hard, so one noisy sample
                    # doesn't erase a real saturation trend.
                    if self._saturation_streak.get(key):
                        self._saturation_streak[key] -= 1

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
        # Bug fix (2026-09-02, "freezing Living Room/Kitchen" incident): snapshot
        # the room_positions this function was HANDED, before any mutation below.
        # This is _auto_calculate's own verdict for every room this cycle —
        # including its occ_bonus-adjusted "needs airflow" math, which is a
        # DIFFERENT (more generous) computation than this function's own
        # beneficiary-margin check below. An OCCUPIED room the base pass already
        # pinned to 100% (past ITS OWN occ_deadband) can fail this function's
        # stricter/differently-computed beneficiary test and still slip through
        # as a donor for someone else's beneficiary — the two checks are meant
        # to agree on "does this occupied room need its own air" but can
        # silently disagree. See the "occupied room qualifies as its own
        # beneficiary but still gets throttled to 0% as a DONOR" bug class in
        # the smart-vent-controller skill. A beneficiary role and a donor role
        # are semantically opposite; a room the house has already decided a
        # PERSON needs full airflow in must never be treated as a source of air
        # for a different room in the same cycle — UNLESS it's donor_only,
        # which is an explicit, deliberate exception (Main Bedroom/Hallway/
        # Laundry Room are meant to donate even while occupied).
        #
        # Deliberately scoped to OCCUPIED rooms only: an EMPTY room pinned to
        # 100% via the hot-override / floor-throttle path is a different,
        # already-correct mechanism (zone-presence-contention donor relaxation,
        # see _donor_cooler_by) that intentionally lets a hot-but-empty room
        # still donate to a genuinely occupied, suffering room elsewhere —
        # protecting that path here would silently defeat it.
        pre_priority_full = {
            k for k, v in room_positions.items()
            if v == 100
            and not ZONES[k[0]]["rooms"][k[1]].get("donor_only")
            and (
                (occ_ent := ZONES[k[0]]["rooms"][k[1]].get("occupancy")) is None
                or self.get_state(occ_ent) == "on"
            )
        }
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

        midday_precool = self.datetime().hour in MIDDAY_PRECOOL_HOURS

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
                # DOWNSTAIRS/BASEMENT LADDER CONSISTENCY (2026-09-02, bug fix):
                # this pass has its OWN, separate "does this room deserve to be
                # pinned to 100% and draft donor CFM" threshold (_room_margin,
                # ~1.5F but reducible by supply/delivery penalties) — totally
                # disconnected from the downstairs-occupied-cooling ladder
                # _auto_calculate just computed for this exact room this exact
                # cycle. Bug this closes: Kitchen at raw +1.2F over setpoint
                # was correctly scored 50% by the ladder, then immediately
                # yanked back to 100% here because 1.2F cleared this
                # function's own (lower, penalty-adjustable) margin — the two
                # thresholds disagreeing produced flapping between 100%
                # (beneficiary) and 0% (donor), NEVER settling at the ladder's
                # correct 50%. For downstairs/basement during COOLING, a room
                # must clear the SAME DOWNSTAIRS_OCC_FULL_THRESHOLD_F (2.0F)
                # the ladder uses for its own 100% tier before it can become a
                # full priority-pass beneficiary (pinned 100%, entitled to
                # draft donor CFM from elsewhere). Below that threshold it is
                # NOT treated as struggling by this pass at all — it stays at
                # whatever the ladder gave it (0% or 50%) and remains fully
                # eligible to be selected as a DONOR for a genuinely
                # struggling room elsewhere (e.g. Game Room) — that donor
                # throttling is correct and desired (per user: comfortable
                # downstairs air should go feed a roasting upstairs), it's
                # the UNCONDITIONAL 100% beneficiary pin below that must not
                # fire before the ladder says a downstairs room has earned it.
                # Heating and upstairs are UNCHANGED (fall through to the
                # original margin-based eligibility check untouched).
                if not heating and zone_name in ("downstairs", "basement"):
                    if off_by(temp) <= DOWNSTAIRS_OCC_FULL_THRESHOLD_F:
                        continue
                    escalated = (off >= PRIORITY_ESCALATE_OVERRIDES.get(key, PRIORITY_ESCALATE_OVER)
                                 or self._delivery_penalty.get(key, 0.0)
                                 >= DELIVERY_ESCALATE_PENALTY)
                    beneficiaries.append((off, key, temp, escalated, is_occupied))
                    continue
                margin = self._room_margin(key, heating)
                eff_margin = (MIDDAY_PRECOOL_MARGIN
                              if (midday_precool and MIDDAY_PRECOOL_MARGIN < margin)
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

        # ── DONOR EXHAUSTION FIX (2026-09-02) ───────────────────────────────
        # Bug found by replaying the live 21:58 log: donors were allocated
        # first-come-first-served, so the WORST room consumed every eligible
        # donor and the second-worst got none:
        #
        #   PASS 1  Game Room 79.3F -> 12 eligible, took ALL 12 -> all to 0%
        #   PASS 2  GB1 76.3F       -> 11 rooms qualified by temperature,
        #                              0 actually available
        #                           -> "struggling but no donor rooms"
        #
        # That log line was NOT "the house is too hot for anyone to donate"
        # (the obvious reading) — it was pure allocation starvation. Raising
        # PRIORITY_MAX_DONORS 8 -> 12 earlier the same evening made it worse:
        # at 8 there were incidentally 4 donors left over for GB1.
        #
        # The fix is a per-beneficiary budget so no single room can drain the
        # pool. NOT an even split: dividing evenly collapses in exactly the
        # case that matters. With 9 beneficiaries (a whole-house-hot evening)
        # an even split gives 12 // 9 = 1 donor each, so the genuinely
        # desperate room gets one donor while eight marginal rooms each get
        # one too. Verified in a replay: Game Room at 80.2F was cut to a
        # single donor that way — strictly worse than the bug being fixed.
        #
        # Instead: rank-weighted with a floor. The worst room keeps roughly
        # half the pool, the next gets half of what remains, and so on, with
        # every beneficiary guaranteed at least one donor. This preserves
        # "concentrate on the worst room" (the whole point of the priority
        # pass) while structurally guaranteeing the runner-up is never left
        # with literally nothing, which is what produced GB1's spurious
        # "struggling but no donor rooms".
        #
        # Note the saturation inversion above overrides this entirely for a
        # duct-limited room: marginal benefit, not need, decides that case.
        n_benef = max(1, len(beneficiaries))
        budget_by_rank = []
        remaining = PRIORITY_MAX_DONORS
        for i in range(n_benef):
            if i == n_benef - 1:
                share = remaining
            else:
                share = max(1, remaining // 2)
            share = max(1, min(share, remaining))
            budget_by_rank.append(share)
            remaining = max(0, remaining - share)

        for rank, (off, key, temp, escalated, _is_occupied) in enumerate(beneficiaries):
            zone_name, room_name = key
            # SATURATION INVERSION (2026-09-02). A room proven duct-limited
            # (see the SATURATION_* constants) gets the OPPOSITE treatment from
            # a normally-struggling room: its own vents still go to 100%, but
            # it may recruit at most SATURATION_MAX_DONORS donors and throttles
            # them only to 50%, never 0%. Rationale, from a physical bag-test
            # measurement: it already receives every CFM its duct can carry, so
            # additional closures cannot help it, and on a constant-torque ECM
            # they actively reduce total house airflow — starving rooms that
            # WOULD have responded. This is also what frees donors for the
            # next-worst beneficiary (the donor-exhaustion fix below).
            saturated = key in self._saturated_rooms
            if saturated:
                donor_pos = PRIORITY_DONOR_POS       # 50%, never 0%
                donor_budget = SATURATION_MAX_DONORS
            else:
                donor_pos = (PRIORITY_DONOR_POS_ESCALATED if escalated
                             else PRIORITY_DONOR_POS)
                donor_budget = budget_by_rank[rank]

            # Pin the beneficiary fully open.
            room_positions[key] = 100

            # Donors: rooms at least PRIORITY_DONOR_COOLER_BY °F more comfortable
            # (cooling: cooler; heating: warmer) than this beneficiary, that are
            # NOT themselves beneficiaries, and aren't already throttled.
            donors = []
            for (zn, rn), pos in room_positions.items():
                if (zn, rn) == key or (zn, rn) in beneficiary_keys:
                    continue
                if (zn, rn) in pre_priority_full:
                    # Fix (2026-09-02): the base pass already decided this room
                    # needs full airflow this cycle (occupied, past its own
                    # occ_deadband) — it is not donor_only, so it must never be
                    # demoted to a donor for a DIFFERENT room's benefit, even if
                    # it didn't independently qualify as a beneficiary under
                    # THIS function's margin math. See snapshot comment above.
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
                if throttled >= donor_budget:
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
            if saturated:
                # Deliberately replaces ESCALATED rather than stacking with it:
                # a saturated room is by definition one that WAS escalated and
                # didn't respond, so showing both would be misleading about
                # what the controller is currently doing to it.
                tag.append("SATURATED")
            elif escalated:
                tag.append("ESCALATED")
            if midday_precool and self._room_margin(key, heating) > MIDDAY_PRECOOL_MARGIN:
                tag.append("pre" + mode_tag)
            tagstr = f" [{','.join(tag)}]"

            if throttled == 0:
                self.log(f"  Priority {room_name} ({temp:.1f}F, off{off:+.1f})"
                         f"{tagstr} struggling but no donor rooms")
            else:
                budget_note = (f", capped at {donor_budget} "
                               f"{'(saturated)' if saturated else '(fair-share)'}")
                self.log(f"  Priority {room_name} ({temp:.1f}F, off{off:+.1f})"
                         f"{tagstr}: pinned 100%, redirected flow from "
                         f"{throttled} room(s) -> {donor_pos}%{budget_note}")

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

    # ── Overnight pre-cool (PHASE 1: foundation layer) ───────────────────────
    # Vent-position pipeline pass + its supporting gate logic. Does NOT touch
    # setpoints at all -- that's a later, separate phase (see the module-level
    # PrecoolGate docstring above and _apply_setpoint_nudge's own docstring).

    def _precool_window_active(self, now=None):
        """True while local time is within the overnight pre-cool window.

        01:00:00 inclusive through 06:30:00 EXCLUSIVE. Compared in minutes-
        since-midnight (NOT hour-only `in range()`) because the end boundary
        falls on a half hour -- an hour-only check would wrongly include all
        of 06:xx.
        """
        if now is None:
            now = self.datetime()
        # Minute-of-day comparison; seconds/microseconds don't matter since
        # both boundaries are defined on whole minutes.
        minutes = now.hour * 60 + now.minute
        start = PRECOOL_WINDOW_START_HOUR * 60 + PRECOOL_WINDOW_START_MIN
        end = PRECOOL_WINDOW_END_HOUR * 60 + PRECOOL_WINDOW_END_MIN
        return start <= minutes < end

    def _precool_window_id_for(self, now=None):
        """Identifier for the CURRENT window-night, used to reset the
        min-temp tracker when a new night's window begins. The window starts
        at 01:00, so any time from 00:00 up to (but not including) the next
        day's 01:00 that is still "tonight's window" maps to the date the
        01:00 boundary falls on. Simplest correct rule for a 01:00-06:30
        window: the window-night id is just today's date while inside the
        window (the window never crosses midnight).
        """
        if now is None:
            now = self.datetime()
        return now.date().isoformat()

    def _precool_reset_if_new_window(self, now=None):
        """Reset the min-temp tracker when a NEW window-night begins.

        Called from _precool_gate() so it happens exactly once per cycle,
        before any min-temp reads/writes for this cycle. Only resets while
        the window is actually active and the stored id is stale -- an old
        night's result must stay visible (via the published sensor) between
        windows, so we don't clear on every cycle, only on entering a new one.
        """
        if now is None:
            now = self.datetime()
        if not self._precool_window_active(now):
            return
        window_id = self._precool_window_id_for(now)
        if self._precool_window_id != window_id:
            self._precool_window_id = window_id
            self._precool_min_temps = {}

    def _precool_update_min_temps(self, now=None):
        """Record each target room's current temp into the min-temp tracker.

        Only meaningful while the window is active (called from
        _precool_gate() after the new-window reset, unconditionally -- if the
        window isn't active this is a harmless no-op since nothing new
        should be tracked, but we still allow the read so a room's min can be
        captured on the very first active cycle of the window).
        """
        if now is None:
            now = self.datetime()
        if not self._precool_window_active(now):
            return
        for key in PRECOOL_TARGETS:
            zone_name, room_name = key
            sensors = ZONES[zone_name]["rooms"][room_name]
            temp = self._read_temp(sensors["temp"])
            if temp is None:
                continue
            prior = self._precool_min_temps.get(key)
            if prior is None or temp < prior:
                self._precool_min_temps[key] = temp

    def _precool_cold_abort(self):
        """True if pre-cool must abort: ANY occupied room, house-wide, reads
        at or below PRECOOL_ABORT_OCCUPIED_F. Unconditional -- applies
        regardless of whether the room is one of the two pre-cool targets.
        Rooms with unreadable temps or that are not occupied are skipped.
        """
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                occ_entity = sensors.get("occupancy")
                if not occ_entity:
                    continue
                if self.get_state(occ_entity) != "on":
                    continue
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                if temp <= PRECOOL_ABORT_OCCUPIED_F:
                    return True
        return False

    def _precool_humidity_ok(self):
        """True if humidity conditions allow pre-cool to engage. FAIL CLOSED.

        Primary gate: dewpoint (sensor.indoor_dew_point) must be readable and
        numeric, and <= PRECOOL_DEWPOINT_MAX_F. Any missing/unavailable/
        unknown/non-numeric reading blocks (fail closed) -- dewpoint LOW is
        good, so absence of a trustworthy reading must NOT default to "ok".

        Backstop: RH (sensor.indoor_humidity_live), only if it IS readable
        and numeric -- if it reads >= PRECOOL_RH_MAX_PCT, block even though
        dewpoint looked fine (catches a frozen/stuck dewpoint sensor). RH
        HIGH is bad. A missing/unreadable RH sensor does NOT block by itself;
        dewpoint is the primary gate and RH is only a backstop against it.
        """
        dp = self._read_temp(PRECOOL_DEWPOINT_ENTITY)
        if dp is None:
            if not self._precool_dewpoint_unavailable_logged:
                self.log(f"  PRE-COOL: {PRECOOL_DEWPOINT_ENTITY} unavailable "
                         f"-> humidity gate fails closed (blocked)")
                self._precool_dewpoint_unavailable_logged = True
            return False
        self._precool_dewpoint_unavailable_logged = False

        if dp > PRECOOL_DEWPOINT_MAX_F:
            if not self._precool_humidity_blocked_logged:
                self.log(f"  PRE-COOL: dewpoint {dp:.1f}F > "
                         f"{PRECOOL_DEWPOINT_MAX_F}F -> blocked")
                self._precool_humidity_blocked_logged = True
            return False

        rh = self._read_temp(PRECOOL_HUMIDITY_ENTITY)
        if rh is not None and rh >= PRECOOL_RH_MAX_PCT:
            if not self._precool_humidity_blocked_logged:
                self.log(f"  PRE-COOL: RH backstop {rh:.1f}% >= "
                         f"{PRECOOL_RH_MAX_PCT}% (dewpoint {dp:.1f}F ok) "
                         f"-> blocked")
                self._precool_humidity_blocked_logged = True
            return False

        self._precool_humidity_blocked_logged = False
        return True

    def _precool_gate(self):
        """Compute the pre-cool engage/no-engage decision ONCE per cycle.

        This is the SINGLE source of truth for whether pre-cool may act.
        BOTH the vent pass (_apply_precool_vents) and the setpoint-nudge
        integration (_precool_demand, consumed by _apply_setpoint_nudge)
        MUST consume this same gate rather than re-deriving window/humidity/
        abort/suppression logic themselves -- this codebase has previously
        been bitten by two logic layers disagreeing about the same threshold
        (see _apply_priority_rooms vs the base ladder).

        PHASE 2 added the human-override suppression condition here, in this
        one function, as the original docstring required. The other condition
        that phase contemplated (`demand > 0`) deliberately did NOT land as a
        gate term: pre-cool's demand is what the gate FEEDS (see
        _precool_demand, which returns 0.0 whenever this gate is inactive), so
        AND-ing demand into `active` would be circular and would additionally
        turn the vent pass off the instant the floors are met -- which is
        wrong, the vents should keep favoring the targets while the window
        runs. The demand==0 case is already handled where it belongs, in the
        nudge's own engage/release comparison.

        Returns a PrecoolGate namedtuple. `active` is the final decision;
        `reason` is a short string for logging/publishing.
        """
        now = self.datetime()
        # Reset + update the min-temp tracker before evaluating the gate so
        # the tracker reflects this cycle's readings.
        self._precool_reset_if_new_window(now)

        window_active = self._precool_window_active(now)
        cold_abort = self._precool_cold_abort()
        humidity_ok = self._precool_humidity_ok()
        # Human-override veto for THIS window-night (see the instance-state
        # comment in initialize()). Compared by window id, never by a bare
        # boolean, so last night's veto can never leak into tonight and
        # tonight's veto can never expire early inside the same night. Read
        # via getattr with a safe default: an offline harness (or a restore
        # path from an OLD-format state file) may not have set the attribute.
        suppressed = bool(
            window_active
            and getattr(self, "_precool_suppressed_window_id", None)
            == self._precool_window_id_for(now))

        if window_active:
            self._precool_update_min_temps(now)

        active = (window_active and not cold_abort and humidity_ok
                  and not suppressed)

        if not window_active:
            reason = "window inactive"
        elif cold_abort:
            reason = "cold-abort: an occupied room is at/below " \
                     f"{PRECOOL_ABORT_OCCUPIED_F}F"
        elif not humidity_ok:
            reason = "humidity gate blocked"
        elif suppressed:
            reason = "suppressed for the rest of this window " \
                     "(human setpoint override)"
        else:
            reason = "active"

        return PrecoolGate(active=active, window_active=window_active,
                            cold_abort=cold_abort, humidity_ok=humidity_ok,
                            reason=reason, suppressed=suppressed)

    def _precool_demand(self, gate=None):
        """Pre-cool's OWN demand value, in °F, for the setpoint nudge.

        Analogous IN SPIRIT to _apply_setpoint_nudge's `worst_excess`, but
        measured against the overnight PRE-COOL FLOORS instead of the comfort
        setpoint + activation margin:

            demand_room = current_temp - floor_temp

        SIGN CONVENTION (a known bug class on this file): POSITIVE means the
        room is still ABOVE its floor, i.e. it still WANTS cooling. The
        overall demand is the MAX across the two PRECOOL_TARGETS rooms,
        floored at 0.0, so it is never negative and a room that has already
        beaten its floor cannot cancel out the other room's real demand.

        Rooms with an unreadable temp are SKIPPED (not treated as 0 demand and
        not treated as infinite demand) -- exactly how worst_excess skips a
        room whose sensor is missing.

        OCCUPANCY DOES NOT GATE THIS, deliberately and unlike worst_excess: a
        sleeping person may never trip a PIR overnight, so requiring occupancy
        would make pre-cool silently not run on precisely the nights it is
        for. The floors themselves (plus the house-wide
        PRECOOL_ABORT_OCCUPIED_F cold-abort inside the gate) ARE the occupant-
        comfort protection.

        Returns exactly 0.0 whenever the pre-cool gate is not active (outside
        the window, cold-abort, humidity-blocked, or human-suppressed), so a
        non-running pre-cool contributes literally nothing to the nudge and
        the nudge behaves byte-identically to its pre-PHASE-2 self.
        """
        if gate is None:
            gate = self._precool_gate()
        if not gate.active:
            return 0.0
        demand = 0.0
        for key, floor in PRECOOL_TARGETS.items():
            zone_name, room_name = key
            sensors = ZONES[zone_name]["rooms"][room_name]
            temp = self._read_temp(sensors["temp"])
            if temp is None:
                continue
            room_demand = temp - floor
            if room_demand > demand:
                demand = room_demand
        # The accumulator starts at 0.0 and only ever increases, so this max()
        # cannot change the value -- it is an explicit restatement of the
        # "never negative" invariant for the reader, not load-bearing logic.
        # Do NOT rewrite the loop to seed `demand` from the first room; that
        # WOULD make a below-floor room able to return a negative demand.
        return max(0.0, demand)

    def _precool_suppress_for_window(self, now=None):
        """Veto pre-cool for the REST of the current window-night.

        Called from the CONFIRMED human-override path in
        _apply_setpoint_nudge (the readback-mismatch-past-CONFIRM_SEC branch
        that also sets _sp_override_cooldown_until). No-op outside the window:
        an override at 15:00 has nothing to do with tonight's pre-cool, and
        pre-emptively vetoing a window that hasn't started would punish the
        user for touching the thermostat during the day.

        Sets ONLY pre-cool's own veto flag. It never touches any _sp_* field,
        so the comfort nudge's engage/release/cooldown behavior is completely
        unchanged by pre-cool's suppression.
        """
        if now is None:
            now = self.datetime()
        if not self._precool_window_active(now):
            return
        window_id = self._precool_window_id_for(now)
        if getattr(self, "_precool_suppressed_window_id", None) == window_id:
            return  # already vetoed this window; don't re-log every cycle
        self._precool_suppressed_window_id = window_id
        self.log(f"  PRE-COOL: human setpoint override detected inside the "
                 f"overnight window -- pre-cool SUPPRESSED for the rest of "
                 f"window-night {window_id} (not just the "
                 f"{SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN}min cooldown)")

    def _apply_precool_vents(self, room_positions, gate):
        """Vent-position pipeline pass for overnight pre-cool.

        No-op (returns room_positions completely UNCHANGED) unless
        gate.active. When active: Game Room + Guest Bedroom 1 vents to 100%.
        Touches NO other room -- every other room, INCLUDING Main Bedroom,
        passes through with whatever value room_positions already holds from
        the earlier passes (_auto_calculate -> _apply_priority_rooms ->
        _apply_fan_assist). Runs between _apply_fan_assist and
        _apply_setpoint_nudge in control_loop; _apply_backpressure_rooms
        still runs last and can still throttle these positions under real
        backpressure.

        Corrected 2026-09-03: this pass used to force Main Bedroom to a fixed
        donor position regardless of its own measured comfort need, stomping
        the base need-based ladder's already-correct value (confirmed live:
        "downstairs/Main Bedroom: 68.7F empty need=-3.3 -> 0% (satisfied
        (-3.3))"). Per the user's explicit correction: "a donor's vent
        position should reflect the donor's OWN comfort need, not a value
        forced by the beneficiary passes." Main Bedroom is intentionally left
        untouched here -- its own need-based logic (already correct, already
        tested) governs it, exactly like every other non-target room, and
        exactly as it did before this feature existed. The PRE-EXISTING,
        separate donor_only mechanism in ZONES (consumed by
        _apply_priority_rooms) still independently decides whether Main
        Bedroom donates air to a DIFFERENT struggling room; that mechanism is
        untouched by this pass.
        """
        if not gate.active:
            return room_positions

        new_positions = dict(room_positions)
        # room_positions is keyed by (zone, room), not by individual vent --
        # the per-vent expansion happens later in control_loop's set-vents
        # loop, which reads each room's ZONES[...]["vents"] list. Setting the
        # room key here is sufficient and matches how every other pass
        # (priority/fan-assist/backpressure) writes room_positions.
        for key in PRECOOL_TARGETS:
            new_positions[key] = 100

        return new_positions

    def _publish_precool_sensor(self, gate):
        """Publish sensor.smart_vent_precool, mirroring the EXACT publishing
        convention of _publish_delivery_penalty / DELIVERY_PENALTY_ENTITY:
        numeric state (as a str -- see the state=str(...) comment on that
        method for why a bare 0.0 float silently drops the state) + a dict
        attribute of per-room detail. Published every cycle (including
        outside the window) so last night's result stays visible until the
        next window.

        deficit_f convention: deficit_f = min_temp_reached_so_far - floor.
        POSITIVE means the floor was NOT reached (min stayed warmer than
        floor); NEGATIVE/zero means the floor was reached or beaten. State =
        the max deficit_f across the two target rooms (0.0 when no reading
        yet / floor already met everywhere).
        """
        try:
            per_room = {}
            deficits = []
            for key, floor in PRECOOL_TARGETS.items():
                zone_name, room_name = key
                min_reached = self._precool_min_temps.get(key)
                deficit_f = (round(min_reached - floor, 2)
                             if min_reached is not None else 0.0)
                deficits.append(deficit_f)
                per_room[room_name] = {
                    "floor_f": floor,
                    "min_reached_f": min_reached,
                    "deficit_f": deficit_f,
                    "window_active": gate.window_active,
                    "reason": gate.reason,
                }
            worst = max(deficits) if deficits else 0.0
            self.set_state(
                PRECOOL_ENTITY,
                state=str(round(worst, 2)),
                attributes={
                    "friendly_name": "Smart Vent Overnight Pre-Cool deficit F",
                    "icon": "mdi:snowflake-thermometer",
                    "active": gate.active,
                    "window_active": gate.window_active,
                    "suppressed": gate.suppressed,
                    "reason": gate.reason,
                    "rooms": per_room,
                },
            )
        except Exception as e:
            self.log(f"pre-cool sensor publish failed (non-fatal): {e}")

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

        The human-override cooldown (`self._sp_override_cooldown_until`) is
        ALWAYS read from instance state, never taken as a parameter here —
        it must survive every subsequent persist call (engage/deepen/release)
        unmodified until it naturally expires, so a caller that doesn't know
        about it can never accidentally clear it by omission. Set it via
        `self._sp_override_cooldown_until = ...` BEFORE calling this, same
        write-ahead discipline as every other _sp_* field.

        The overnight pre-cool suppression flag
        (`self._precool_suppressed_window_id`) and the per-window min-temp
        tracker (`self._precool_min_temps` + `self._precool_window_id`) follow
        that SAME discipline for the SAME reason: they are sticky, they are
        read from instance state here rather than passed in, and no caller can
        clear them by omission. The suppression flag in particular MUST survive
        a restart -- an AppDaemon restart mid-window would otherwise resurrect
        a pre-cool the human already vetoed, which is the exact restart-amnesia
        class of bug this file's persistence exists to prevent.

        NUDGE_STATE_VERSION stays 1 on purpose despite the added keys. Bumping
        it would make every existing state file on the live house fail the
        version check and get DISCARDED, forfeiting restart-amnesia protection
        for any in-flight comfort nudge at deploy time — a real regression to
        buy nothing. The new keys are purely ADDITIVE and every reader uses
        .get() with a safe default, so an OLD-format file (written before this
        deploy, lacking all of them) restores exactly as it did before.

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
            override_cooldown_until = getattr(
                self, "_sp_override_cooldown_until", None)
            # OVERNIGHT PRE-COOL (PHASE 2) sticky fields. Read from instance
            # state here, NEVER passed as parameters — same discipline as the
            # override cooldown above, so no caller can clear them by omission.
            precool_suppressed_window_id = getattr(
                self, "_precool_suppressed_window_id", None)
            precool_window_id = getattr(self, "_precool_window_id", None)
            # The min-temp tracker is keyed by a (zone, room) TUPLE, which JSON
            # cannot represent as an object key. Serialize as a list of
            # [zone, room, temp] triples and rebuild the tuple keys on restore.
            precool_min_temps = [
                [k[0], k[1], float(v)]
                for k, v in (getattr(self, "_precool_min_temps", None)
                             or {}).items()
            ]
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
                # Human-override cooldown (2026-09-02): ISO-8601 UTC, or None.
                # Persisted unconditionally so an app restart mid-cooldown
                # cannot amnesia it away and re-engage early.
                "override_cooldown_until": (
                    None if override_cooldown_until is None
                    else override_cooldown_until.strftime("%Y-%m-%dT%H:%M:%SZ")),
                # Overnight pre-cool (PHASE 2, 2026-09-02). ADDITIVE keys only;
                # NUDGE_STATE_VERSION deliberately stays 1 (see docstring).
                # precool_suppressed_window_id is the load-bearing one: it is
                # the human's overnight veto and must not amnesia away.
                "precool_suppressed_window_id": precool_suppressed_window_id,
                "precool_window_id": precool_window_id,
                "precool_min_temps": precool_min_temps,
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
            # OVERNIGHT PRE-COOL (PHASE 2): restore FIRST, and REGARDLESS of
            # `owned`, for the same reason as the cooldown below — the human's
            # overnight veto is recorded alongside owned=False and is exactly
            # the record a restart must not amnesia away. Restored before any
            # of the ownership validation that can `raise` into the discard
            # handler, so a corrupt/incomplete OWNERSHIP record can never also
            # throw away a valid pre-cool veto (conservative direction: when in
            # doubt, keep pre-cool suppressed).
            #
            # EVERY key below is read with .get() and a safe default, so an
            # OLD-FORMAT file written before this deploy (which has none of
            # them) restores without raising and simply leaves pre-cool state
            # at its initialize() defaults. This is why NUDGE_STATE_VERSION can
            # stay 1.
            suppressed_id = data.get("precool_suppressed_window_id")
            if isinstance(suppressed_id, str):
                self._precool_suppressed_window_id = suppressed_id
                self.log(f"  PRE-COOL: restored human-override suppression for "
                         f"window-night {suppressed_id} — pre-cool stays "
                         f"vetoed for the rest of that window")
            window_id = data.get("precool_window_id")
            if isinstance(window_id, str):
                self._precool_window_id = window_id
            # Rebuild the tuple-keyed min-temp tracker from its [zone, room,
            # temp] triples. Any malformed entry is skipped individually rather
            # than failing the whole restore: this tracker is observability
            # only (it feeds the published deficit sensor), never a control
            # decision, so a partial rebuild is strictly better than discarding
            # the ownership record over it. _precool_reset_if_new_window() will
            # clear it anyway the moment a NEW window-night starts.
            min_temps_raw = data.get("precool_min_temps")
            if isinstance(min_temps_raw, list):
                restored_min = {}
                for entry in min_temps_raw:
                    if (isinstance(entry, (list, tuple)) and len(entry) == 3
                            and isinstance(entry[0], str)
                            and isinstance(entry[1], str)
                            and isinstance(entry[2], (int, float))):
                        restored_min[(entry[0], entry[1])] = float(entry[2])
                self._precool_min_temps = restored_min
            # HUMAN-OVERRIDE COOLDOWN (2026-09-02): restore this REGARDLESS of
            # `owned` — the whole point is that a just-detected override
            # persists owned=False alongside the cooldown timestamp, and this
            # is exactly the record an app restart must not amnesia away. Parse
            # defensively (missing/corrupt/expired -> just None, never raises)
            # since a cooldown parse failure must not block the rest of restore.
            cooldown_raw = data.get("override_cooldown_until")
            if isinstance(cooldown_raw, str):
                try:
                    cooldown_ts = datetime.strptime(cooldown_raw,
                                                     "%Y-%m-%dT%H:%M:%SZ")
                    if cooldown_ts > self.datetime():
                        self._sp_override_cooldown_until = cooldown_ts
                        self.log(f"  SETPOINT-NUDGE: restored human-override "
                                 f"cooldown, no new nudge until "
                                 f"{cooldown_ts.isoformat()}")
                except (ValueError, TypeError):
                    pass  # corrupt cooldown field -> treat as no cooldown
            if not data.get("owned"):
                # A clean relinquish/release wrote owned=False, or the previous
                # run correctly discarded on a mismatch: not re-adopting is
                # correct either way. The cooldown (if any) was already
                # restored above regardless of this early return.
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

    def _cloud_truth_setpoints(self):
        """Read the ecobee cloud-truth desiredCool/desiredHeat (°F) sensors.

        Returns (cool, heat) as floats, or None on EACH axis that is missing /
        None / 'unknown' / 'unavailable' / non-numeric. The caller must treat
        the read as USABLE only when BOTH axes return a float, because a hold
        written on one axis couples the other (TRAP 1 heatCoolMinDelta) and a
        half-truth is no truth at all.

        These sensors (SETPOINT_TRUTH_COOL / SETPOINT_TRUTH_HEAT) are the
        ecobee runtime's AUTHORITATIVE desiredCool/desiredHeat — the live
        setpoints the cloud actually holds, force-refreshed by the integration
        right after any write. The nudge's ownership readback and engage
        baseline MUST come from here; the homekit_controller mirror
        (THERMOSTAT / climate.ecobee_thermostat) does not reflect a cloud-side
        hold (it kept reporting 66/60 during a real hold of cool 63/heat 57),
        which drove the live relinquish/re-engage churn loop.
        """
        def _f(entity):
            state = self.get_state(entity)
            if state is None:
                return None
            try:
                return float(state)
            except (ValueError, TypeError):
                return None
        return _f(SETPOINT_TRUTH_COOL), _f(SETPOINT_TRUTH_HEAT)

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
                              target_heat, mode="Auto", precool_gate=None):
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

        OVERNIGHT PRE-COOL (PHASE 2, 2026-09-02) -- SECOND DEMAND SOURCE, NOT A
        SECOND WRITER. This function remains the SOLE writer of a thermostat
        setpoint in this app; a second writer would command a value this
        function never issued, its own readback validation would see a setpoint
        it did not command, conclude a human changed it, and latch the 2h
        human-override cooldown. Pre-cool therefore feeds in only as a demand
        VALUE (_precool_demand, measured from the overnight FLOORS), combined
        with comfort's worst_excess via MAX -- never SUM. MAX, because the two
        are independent reasons to want the same single lever moved, not two
        additive requests; and because SETPOINT_NUDGE_MAX_F is a TOTAL cap that
        pre-cool SHARES, it does not get its own extra 2F. There is exactly ONE
        depth computation (_commanded_setpoints), fed the combined effective
        excess, so the two demand sources can never disagree about a threshold
        (the Kitchen/priority-pass two-layers bug class).

        The RELEASE gate is likewise extended, and ONLY while pre-cool is in its
        active window: release then requires BOTH comfort satisfied (<=
        SETPOINT_NUDGE_RELEASE_F) AND pre-cool satisfied (<=
        PRECOOL_NUDGE_RELEASE_F). Releasing on comfort alone while pre-cool
        still wants engagement pops the hold and re-engages on the very next
        cycle -- chatter, every cycle, all night. OUTSIDE the window
        precool_demand is exactly 0.0 and the extra term is vacuously true, so
        the release gate is byte-identical to its pre-PHASE-2 behavior.

        `precool_gate` is the PrecoolGate computed ONCE per cycle by
        control_loop and passed down (the same "compute once in the caller,
        pass it in" discipline `dual` and _commanded_setpoints already use, so
        the vent pass and this pass can never evaluate a different gate within
        one cycle). None means "pre-cool is not participating in this call" and
        yields precool_demand == 0.0 -- i.e. exactly today's pre-PHASE-2
        behavior. That default is the conservative direction (when in doubt,
        suppress pre-cool, never the reverse) and it is what an offline harness
        that only exercises the comfort axis gets.
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

        # ------------------------------------------- Pre-cool demand (PHASE 2)
        # The SECOND demand source. 0.0 whenever pre-cool isn't gated active
        # (no gate passed, outside the window, cold-abort, humidity-blocked, or
        # human-suppressed), which makes every expression below collapse to its
        # pre-PHASE-2 form exactly. `precool_window` is read from the SAME gate
        # object, never re-derived from the clock here, so the release gate and
        # the demand can never disagree about whether pre-cool is running.
        precool_demand = (0.0 if precool_gate is None
                          else self._precool_demand(precool_gate))
        precool_window = bool(precool_gate is not None and precool_gate.active)
        # ONE combined demand feeds the ONE existing depth computation
        # (_commanded_setpoints). MAX, not SUM: SETPOINT_NUDGE_MAX_F is a TOTAL
        # cap shared by both sources, so the deeper of the two independent
        # requests wins and neither can stack past the cap.
        effective_excess = max(worst_excess, precool_demand)

        # ---------------------------------------------------------------- State
        now = self.datetime()
        # TRAP 1 coupling is only relevant in a dual-setpoint (heat_cool/auto)
        # mode. Read `dual` ONCE for this whole cycle; it drives both the engage
        # and any re-nudge so the two can never disagree about the gap.
        dual = hvac_mode in ("heat_cool", "auto")

        if not getattr(self, "_sp_owned", False):
            # DISABLED (see SETPOINT_NUDGE_ENABLED comment at the constant
            # block, 2026-09-02): never engage a brand-new nudge while the
            # mechanism is disabled. Nothing else in this function changes —
            # if a nudge was somehow already owned from before the disable
            # (e.g. mid-flip deploy), the owned branch below still runs its
            # normal readback-guarded release path, so a stale hold still
            # gets safely handed back rather than being abandoned live.
            if not SETPOINT_NUDGE_ENABLED:
                return
            # HUMAN-OVERRIDE COOLDOWN (2026-09-02): a detected human setpoint
            # change blocks ALL new engagement until the cooldown expires,
            # unconditionally — checked BEFORE the worst_excess/ENGAGE_F gate
            # below so a still-hot room can never re-trigger the mechanism
            # early. Cleared naturally once `now` passes the timestamp; no
            # explicit clear-on-expiry needed since every check is a live
            # comparison against `now`, never a stale cached boolean.
            cooldown_until = getattr(self, "_sp_override_cooldown_until", None)
            if cooldown_until is not None:
                if now < cooldown_until:
                    return
                # Cooldown has naturally expired — clear it so we stop
                # persisting a stale future timestamp on the next state write.
                self._sp_override_cooldown_until = None
            # NOT owned. Engage only if the worst occupied excess clears the
            # engage threshold (with hysteresis below via the release bound), AND
            # only while actually conditioning. While idle/fan we engage nothing:
            # engaging a brand-new setpoint hold on a compressor that isn't even
            # running would just push the whole house's setpoint for no reason
            # (the escalation a nudge drives only happens once it runs) — and it
            # would write-churn on every idle/fan cycle. The compressor will
            # re-engage on its own schedule and we can nudge then.
            if effective_excess < SETPOINT_NUDGE_ENGAGE_F:
                return
            if not actively_conditioning:
                return
            # Baseline = the CURRENT live setpoints (the user's own effective
            # setpoint — schedule or their manual hold), read from the ecobee
            # CLOUD TRUTH, NOT the homekit_controller mirror: the mirror does
            # not reflect a cloud-side hold, so capturing it would record a
            # stale/wrong baseline (the live log showed `baseline cool 66.0` for
            # a real hold of cool 63). Cloud truth is the only trustworthy
            # measure of what the user's setpoint actually is right now.
            truth_cool, truth_heat = self._cloud_truth_setpoints()
            # CRITICAL SAFETY: a nudge may NOT engage without a trustworthy 2-axis
            # baseline. If cloud truth is missing / None / 'unknown' /
            # 'unavailable' / non-numeric on EITHER axis, do NOT engage — there is
            # no trustworthy baseline to compute the command off of, so we stay
            # not-owned and simply wait for the sensors to recover. Log at most
            # once per occurrence, not on every 120s cycle. (Relinquish is
            # separately guarded in the owned branch; this is the not-owned twin.)
            if truth_cool is None or truth_heat is None:
                if self._sp_truth_unavailable_logged is not True:
                    self._sp_truth_unavailable_logged = True
                    self.log(f"  SETPOINT-NUDGE: cloud-truth setpoint sensor "
                             f"unavailable (cool={truth_cool}, heat={truth_heat}); "
                             f"NOT engaging — no trustworthy baseline")
                return
            self._sp_truth_unavailable_logged = False
            baseline_cool = truth_cool
            baseline_heat = truth_heat
            commanded_cool, commanded_heat = self._commanded_setpoints(
                baseline_cool, baseline_heat, heating, effective_excess, dual)
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
            if precool_demand > 0.0:
                self.log(f"  SETPOINT-NUDGE: pre-cool demand {precool_demand:.2f}F "
                         f"is a second demand source (effective excess "
                         f"{effective_excess:.2f}F = max of the two; the "
                         f"{SETPOINT_NUDGE_MAX_F}F cap is SHARED)")
            return

        # ------------------------------------------------------------- Owned.
        # Ownership readback comes from the ecobee CLOUD TRUTH (desiredCool/
        # desiredHeat sensors), NOT the homekit_controller mirror (target_cool/
        # target_heat). The mirror does not reflect a cloud-side hold — it kept
        # reporting the PRE-hold values (66/60) while the real hold was cool 63 /
        # heat 57 — so value-matching against it failed every cycle and the app
        # spurious-relinquished then re-engaged (~10 min churn loop, live log
        # 13:13->14:06). Reading cloud truth makes the value-match honest.
        truth_cool, truth_heat = self._cloud_truth_setpoints()
        # CRITICAL SAFETY: if cloud truth is missing / None / 'unknown' /
        # 'unavailable' / non-numeric on EITHER axis, we make NO ownership
        # decision this cycle — no relinquish, no re-baseline, no service call.
        # Relinquishing on an unknown readback is exactly what produced churn,
        # and holding state is safe: the ecobee hold is holdType=nextTransition
        # and expires on its own. Log at most once per occurrence, not on every
        # 120s cycle.
        if truth_cool is None or truth_heat is None:
            if self._sp_truth_unavailable_logged is not True:
                self._sp_truth_unavailable_logged = True
                self.log(f"  SETPOINT-NUDGE: cloud-truth setpoint sensor "
                         f"unavailable (cool={truth_cool}, heat={truth_heat}); "
                         f"making NO ownership decision this cycle — holding "
                         f"state, will expire on its own")
            return
        self._sp_truth_unavailable_logged = False
        live_cool = truth_cool
        live_heat = truth_heat

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
                #
                # HUMAN-OVERRIDE COOLDOWN (2026-09-02): a confirmed override is
                # not just "relinquish and wait for the normal engage gate" --
                # it starts a real cooldown window during which NO new nudge
                # may engage at all, even if the room is still hot. Without
                # this, a human correcting the thermostat gets fought again
                # within one CONFIRM_SEC cycle (~7 min) the moment worst_excess
                # re-clears ENGAGE_F -- which for a chronically hot room is
                # almost immediately. "Anything done by a human on the
                # thermostat is THE be-all end-all" (user, 2026-09-02).
                self._sp_override_cooldown_until = now + timedelta(
                    minutes=SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN)
                # OVERNIGHT PRE-COOL (PHASE 2): the 2h cooldown is not enough
                # for pre-cool. If this override happened INSIDE the overnight
                # window, the cooldown could expire while the SAME window is
                # still open (e.g. override at 01:15 -> cooldown ends 03:15,
                # window runs to 06:30) and pre-cool would quietly resume the
                # very night the human vetoed it. So pre-cool is additionally
                # suppressed for the REST of that window-night. This touches
                # ONLY pre-cool's own flag -- the comfort nudge's cooldown
                # semantics above are completely unchanged. Outside the window
                # this is a no-op (see _precool_suppress_for_window).
                self._precool_suppress_for_window(now)
                self.log(f"  SETPOINT-NUDGE: user changed setpoint (cool "
                         f"{self._sp_commanded_cool:.1f} -> {live_cool} live), "
                         f"relinquishing ownership without resuming — cooldown "
                         f"until {self._sp_override_cooldown_until.isoformat()} "
                         f"(no new nudge for {SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN} min)")
                # Persist the relinquishment BEFORE clearing in-memory state, so
                # a crash mid-transition cannot leave a stale "we own it" record.
                # The user's live value becomes the baseline for any future
                # engagement once they release it back to schedule. The
                # cooldown timestamp (set above, on self) is persisted
                # automatically — it cannot amnesia away and re-engage early.
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

        # RELEASE GATE. Comfort's own condition is UNCHANGED. The pre-cool term
        # is added ONLY while pre-cool is actually gated active this cycle: with
        # precool_window False (every cycle outside the window, and every cycle
        # pre-cool is aborted/blocked/suppressed) `precool_satisfied` is True by
        # construction, so this reduces EXACTLY to the pre-PHASE-2
        # `worst_excess <= SETPOINT_NUDGE_RELEASE_F`.
        #
        # Why the AND is required inside the window (the chatter bug): comfort
        # is satisfied long before the overnight floors are reached, so
        # releasing on comfort alone pops the hold, pre-cool's still-positive
        # demand immediately re-clears ENGAGE_F on the next cycle, and the
        # mechanism engages again -- pop/re-engage every cycle, all night, each
        # cycle a real ecobee write. Requiring BOTH to be satisfied means the
        # nudge stays continuously OWNED through the window instead: one engage,
        # zero releases, which is the entire point of pre-cool being a second
        # DEMAND SOURCE rather than a deeper nudge.
        precool_satisfied = (not precool_window
                             or precool_demand <= PRECOOL_NUDGE_RELEASE_F)
        if worst_excess <= SETPOINT_NUDGE_RELEASE_F and precool_satisfied:
            # Satisfied (or room recovered) enough — pop our own hold. ONLY safe
            # because readback still matches (TRAP 2). Clears all _sp_* state.
            self._release_setpoint_nudge()
            self.log(f"  SETPOINT-NUDGE: released (worst_excess {worst_excess:.2f}F "
                     f"<= release {SETPOINT_NUDGE_RELEASE_F:.2f}F)")
            return
        if worst_excess <= SETPOINT_NUDGE_RELEASE_F and not precool_satisfied:
            # Comfort alone would have released. Held instead, on pre-cool's
            # demand. Logged so the overnight hold is explainable from the log
            # rather than looking like a stuck nudge.
            self.log(f"  SETPOINT-NUDGE: comfort satisfied (worst_excess "
                     f"{worst_excess:.2f}F) but HELD for pre-cool demand "
                     f"{precool_demand:.2f}F > release "
                     f"{PRECOOL_NUDGE_RELEASE_F:.2f}F (no release/re-engage "
                     f"chatter)")

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
            effective_excess, dual)
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
