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
            },
            "Main Bathroom": {
                "temp": "sensor.main_bathroom_temperature",
                "occupancy": "binary_sensor.main_bathroom_occupancy",
                "vents": [
                    "cover.main_bathroom_f586_vent_2",
                ],
            },
            "Hallway": {
                "temp": "sensor.hallway_temperature",
                "occupancy": None,
                "vents": [
                    "cover.hallway_907e_vent_2",
                ],
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

# Backpressure: never close more than this fraction of total vents
MAX_CLOSED_RATIO = 0.60

# How far a room temp can be from setpoint before we react (°F)
DEADBAND = 1.0

# Hysteresis: once a vent opens, the zone must drop this far BELOW the
# close threshold before we actually close it. Prevents flapping at setpoint.
HYSTERESIS = 0.5

# Cycle interval in seconds
CYCLE_INTERVAL = 120

# After a manual override via HA UI, hold that position for this long
MANUAL_HOLD_MINUTES = 60

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
# above it, but a room 3°F+ cooler than the struggling room still has plenty of
# margin to give up some airflow. Donors are throttled to 50% (never closed), so
# they keep getting half their flow and won't run away from setpoint.
PRIORITY_DONOR_COOLER_BY = 3.0
# Throttle position for donor rooms (Flair vents are 0/50/100 only).
PRIORITY_DONOR_POS = 50
# Never throttle more than this many donor rooms per beneficiary room.
PRIORITY_MAX_DONORS = 4
# Escalation: when a beneficiary is THIS far over the cool setpoint, it's not
# just lagging, it's losing. Throttle donors all the way to 0% (closed) instead
# of 50% to dump maximum CFM into it. The backpressure pass still caps total
# closures at MAX_CLOSED_RATIO, so this can't choke the system.
PRIORITY_ESCALATE_OVER = 4.0
PRIORITY_DONOR_POS_ESCALATED = 0

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

        # Run the control loop
        self.run_every(self.control_loop, "now+10", CYCLE_INTERVAL)

        # Listen for manual vent changes (user moved a vent in the UI)
        all_vents = _get_all_vents()
        for vent in all_vents:
            self.listen_state(self.on_vent_manual_change, vent,
                              attribute="current_tilt_position")

        # Listen for occupancy changes to react immediately
        for zone in ZONES.values():
            for room_name, sensors in zone["rooms"].items():
                occ = sensors.get("occupancy")
                if occ:
                    self.listen_state(self.on_occupancy_change, occ)

        # Listen for mode changes to run immediately
        self.listen_state(self.on_mode_change, MODE_SELECT)
        self.listen_state(self.on_mode_change, ENABLED_SWITCH)

        self.log(f"Smart Vent Controller ready. {len(all_vents)} vents across "
                 f"{len(ZONES)} zones. Cycle every {CYCLE_INTERVAL}s.")

    # ── Event handlers ────────────────────────────────────────────────────────

    def on_vent_manual_change(self, entity, attribute, old, new, kwargs):
        """Detect when a user manually moves a vent (not us)."""
        if entity in self._last_positions:
            # If we just set this, ignore the state callback
            if self._last_positions[entity] == new:
                return
        # User moved it manually — hold their position
        self._manual_holds[entity] = datetime.now() + timedelta(
            minutes=MANUAL_HOLD_MINUTES
        )
        self.log(f"Manual override detected: {entity} -> {new}%, "
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

        # Refresh measured per-room supply penalties whenever air is moving;
        # duct temps are only meaningful with airflow. These drive each room's
        # activation margin (handicapped rooms react earlier) automatically. The
        # handicap is mode-correct: warmest-supply-wins when heating, coldest
        # when cooling. (Skip on "fan" — no conditioned air, so no real penalty.)
        if hvac_action in ("cooling", "heating"):
            self._update_supply_penalties(heating=(hvac_action == "heating"))

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
            room_positions, hvac_action, target_cool, target_heat
        )

        # Fan-assist redistribution: when the system is idle but a room is still
        # off-target and oppositely-conditioned air is banked elsewhere, run the
        # blower and shove that banked air where it's needed (cold air to a hot
        # room when cooling; warm air to a cold room when heating). Manages the
        # fan mode and may rewrite room_positions. Runs before backpressure.
        room_positions = self._apply_fan_assist(
            room_positions, mode, hvac_action, target_cool, target_heat
        )

        # Apply backpressure protection
        room_positions = self._apply_backpressure_rooms(room_positions)
        # Set vents per room
        for (zone_name, room_name), position in room_positions.items():
            room = ZONES[zone_name]["rooms"][room_name]
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
                prev = self._last_zone_positions.get(key)

                if need > DEADBAND * 3:
                    pos = 100
                    reason = f"high need ({need:+.1f})"
                elif need > DEADBAND:
                    pos = 100
                    reason = f"needs airflow ({need:+.1f})"
                elif need > -DEADBAND:
                    if is_occupied:
                        pos = 50
                        reason = f"near setpoint, occupied ({need:+.1f})"
                    else:
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

    def _room_margin(self, key, heating=False):
        """Activation margin (°F past the active setpoint) for a room.

        Derived from the room's measured supply-air penalty (which is already
        mode-correct from _update_supply_penalties), amplified by how extreme it
        is outside. A handicapped room gets a lower (earlier-engaging) margin
        automatically, in BOTH heating and cooling. Override, if present, wins.
        """
        if key in PRIORITY_MARGIN_OVERRIDES:
            return PRIORITY_MARGIN_OVERRIDES[key]
        penalty = self._supply_penalty.get(key, 0.0)
        margin = (PRIORITY_MARGIN_BASE
                  - PRIORITY_PENALTY_GAIN * penalty * self._weather_factor(heating))
        return max(PRIORITY_MARGIN_MIN, min(PRIORITY_MARGIN_BASE, margin))

    def _apply_priority_rooms(self, room_positions, hvac_action,
                              target_cool, target_heat=None):
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
        """
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
        beneficiaries = []  # (off, key, temp, escalated)
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                occ_entity = sensors.get("occupancy")
                if occ_entity and self.get_state(occ_entity) != "on":
                    continue  # only help occupied rooms
                margin = self._room_margin(key, heating)
                eff_margin = (PRECOOL_MARGIN
                              if (precool and PRECOOL_MARGIN < margin)
                              else margin)
                off = off_by(temp)
                if off <= eff_margin:
                    continue
                escalated = off >= PRIORITY_ESCALATE_OVER
                beneficiaries.append((off, key, temp, escalated))

        if not beneficiaries:
            return room_positions

        beneficiaries.sort(reverse=True)  # largest deviation first
        beneficiary_keys = {b[1] for b in beneficiaries}

        for off, key, temp, escalated in beneficiaries:
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
                if heating:
                    if dtemp < temp + PRIORITY_DONOR_COOLER_BY:
                        continue  # not enough warmer than the cold beneficiary
                else:
                    if dtemp > temp - PRIORITY_DONOR_COOLER_BY:
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
        setpoint = target_heat if heating else target_cool

        def off_by(t):
            return (setpoint - t) if heating else (t - setpoint)

        # Beneficiaries: occupied rooms far enough off-target to warrant it.
        beneficiaries = []  # (off, key, temp)
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
                key = (zone_name, room_name)
                temp = self._read_temp(sensors["temp"])
                if temp is None:
                    continue
                occ_entity = sensors.get("occupancy")
                if occ_entity and self.get_state(occ_entity) != "on":
                    continue
                if off_by(temp) < FAN_ASSIST_OVER:
                    continue
                beneficiaries.append((off_by(temp), key, temp))

        beneficiaries.sort(reverse=True)  # worst-off first
        beneficiary_keys = {b[1] for b in beneficiaries}

        engaged_any = False
        for off, key, temp in beneficiaries:
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
            for dkey, docc, dtemp in donors:
                if throttled >= PRIORITY_MAX_DONORS:
                    break
                room_positions[dkey] = 0
                throttled += 1

            kind = "warm" if heating else "cold"
            self.log(f"  FAN-ASSIST {room_name} ({temp:.1f}F, off{off:+.1f}, "
                     f"{'heat' if heating else 'cool'}, hvac={hvac_action}): "
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
        for zone_name, zone in ZONES.items():
            for room_name, sensors in zone["rooms"].items():
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

    def _engage_fan_assist(self):
        """Turn the air handler fan to 'on', tracking that WE did it."""
        if getattr(self, "_fan_assist_active", False):
            return
        current = self.get_state(FAN_ENTITY, attribute="fan_mode")
        if current == "on":
            # Already on (user or schedule); don't claim ownership so we won't
            # turn it off later and stomp their setting.
            return
        self.log("  FAN-ASSIST: setting ecobee fan_mode -> on")
        self.call_service("climate/set_fan_mode",
                          entity_id=FAN_ENTITY, fan_mode="on")
        self._fan_assist_active = True

    def _release_fan_assist(self):
        """Return the fan to 'auto' only if WE turned it on."""
        if not getattr(self, "_fan_assist_active", False):
            return
        self.log("  FAN-ASSIST: releasing ecobee fan_mode -> auto")
        self.call_service("climate/set_fan_mode",
                          entity_id=FAN_ENTITY, fan_mode="auto")
        self._fan_assist_active = False

    # ── Backpressure protection ───────────────────────────────────────────────

    def _apply_backpressure_rooms(self, room_positions):
        """Ensure we don't close more than MAX_CLOSED_RATIO of total vents."""

        total_vents = len(_get_all_vents())
        max_closed = int(total_vents * MAX_CLOSED_RATIO)

        # Count vents that would be closed
        closed_count = 0
        for (zone_name, room_name), pos in room_positions.items():
            if pos == 0:
                closed_count += len(ZONES[zone_name]["rooms"][room_name].get("vents", []))

        if closed_count <= max_closed:
            return room_positions

        self.log(f"Backpressure: {closed_count} vents would close, "
                 f"max allowed {max_closed}. Opening rooms to 50%.")

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
        self.call_service(
            "cover/set_cover_tilt_position",
            entity_id=entity,
            tilt_position=position,
        )
        self._last_positions[entity] = position
