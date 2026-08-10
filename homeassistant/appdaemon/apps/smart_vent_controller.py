"""Smart Vent Controller for Flair vents.

Zones airflow by floor using room temperature, occupancy, and ecobee state.
Respects manual overrides. Proportional control (0/50/100%).
Backpressure-aware: never closes more than 60% of total vents.

Controls:
  input_boolean.vent_control_enabled  - master on/off
  input_select.vent_control_mode      - Auto / Manual / Cool Upstairs / Cool Downstairs
"""

import re

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
                hvac_mode, hvac_action, target_cool, target_heat
            )

        # Concentrate airflow toward any struggling room by throttling already-
        # comfortable rooms. Symmetric: helps hot rooms when cooling, cold rooms
        # when heating. Must run BEFORE backpressure so backpressure remains the
        # final safety net.
        room_positions = self._apply_priority_rooms(
            room_positions, hvac_action, target_cool, target_heat, mode
        )

        # Fan-assist redistribution: when the system is idle but a room is still
        # off-target and oppositely-conditioned air is banked elsewhere, run the
        # blower and shove that banked air where it's needed (cold air to a hot
        # room when cooling; warm air to a cold room when heating). Manages the
        # fan mode and may rewrite room_positions. Runs before backpressure.
        room_positions = self._apply_fan_assist(
            room_positions, mode, hvac_action, target_cool, target_heat
        )

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

                if need > OCCUPANCY_OVERRIDE_OVER:
                    pos = 100
                    reason = f"hot override ({need:+.1f}) — 100% regardless of occupancy"
                elif need > unocc_hot_override and not is_occupied:
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
                if occ_entity and not is_occupied:
                    if off < OCCUPANCY_OVERRIDE_OVER:
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
                escalated = (off >= PRIORITY_ESCALATE_OVER
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
                self.log(f"  Priority {room_name} ({temp:.1f}F): throttling "
                         f"{dkey[0]}/{dkey[1]} ({dtemp:.1f}F, "
                         f"{'occ' if docc else 'empty'}) -> {donor_pos}%")

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
                if occ_entity and self.get_state(occ_entity) != "on":
                    if off < OCCUPANCY_OVERRIDE_OVER:
                        continue
                margin = self._room_margin(key, heating, base_margin=FAN_ASSIST_OVER)
                if off < margin:
                    continue
                escalated = (off >= PRIORITY_ESCALATE_OVER
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
                    if heating:
                        useful = dtemp >= temp + FAN_ASSIST_DONOR_COOLER_BY
                    else:
                        useful = dtemp <= temp - FAN_ASSIST_DONOR_COOLER_BY
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
