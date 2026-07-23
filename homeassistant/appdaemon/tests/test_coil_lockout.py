"""Offline unit test for the dry-coil fan-assist lockout.

Stubs appdaemon.plugins.hass.hassapi so smart_vent_controller imports without
AppDaemon installed, then subclasses the controller with a fake HA state map.
Drives _apply_fan_assist directly and asserts the blower is/ isn't engaged.
"""
import sys
import types
from datetime import datetime, timedelta

# ── Stub the appdaemon import chain ────────────────────────────────────────────
ad = types.ModuleType("appdaemon")
plugins = types.ModuleType("appdaemon.plugins")
hassmod = types.ModuleType("appdaemon.plugins.hass")
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")


class _Hass:  # minimal base class
    def __init__(self, *a, **k):
        pass


hassapi.Hass = _Hass
sys.modules["appdaemon"] = ad
sys.modules["appdaemon.plugins"] = plugins
sys.modules["appdaemon.plugins.hass"] = hassmod
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

sys.path.insert(0, "/Users/adam.durham/repos/homelab/homeassistant/appdaemon/apps")
import smart_vent_controller as svc  # noqa: E402

NOW = datetime(2026, 6, 10, 14, 0, 0)


class FakeController(svc.SmartVentController):
    """Controller with a scriptable HA state map; records fan calls."""

    def __init__(self, temps, occ, fan_mode="auto"):
        self._temps = temps          # entity -> value (str/num)
        self._occ = occ              # entity -> "on"/"off"
        self._fan_mode = fan_mode
        self.fan_calls = []          # list of fan_mode values set
        self._fan_assist_active = False
        self._cooling_ended_at = None
        self._supply_penalty = {}
        self._delivery_penalty = {}
        self.logs = []

    # --- HA shims -------------------------------------------------------------
    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def datetime(self, aware=False):
        return NOW

    def get_state(self, entity, attribute=None):
        if entity == svc.FAN_ENTITY and attribute == "fan_mode":
            return self._fan_mode
        if entity in self._occ:
            return self._occ[entity]
        if entity in self._temps:
            return self._temps[entity]
        return None

    def call_service(self, service, **kwargs):
        if service == "climate/set_fan_mode":
            self._fan_mode = kwargs.get("fan_mode")
            self.fan_calls.append(kwargs.get("fan_mode"))


def build(hot_room_temp, donor_temp, cooling_ended_min_ago):
    """One hot occupied upstairs room + one cold occupied basement donor."""
    # Default everyone comfortable & unoccupied.
    temps, occ = {}, {}
    for zname, zone in svc.ZONES.items():
        for rname, s in zone["rooms"].items():
            temps[s["temp"]] = 72.0
            if s.get("occupancy"):
                occ[s["occupancy"]] = "off"
    # Hot room: Guest Bedroom 1 (upstairs), occupied.
    gb1 = svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]
    temps[gb1["temp"]] = hot_room_temp
    occ[gb1["occupancy"]] = "on"
    # Donor: Main Bedroom (downstairs), cold, occupied so direction sees it too.
    donor = svc.ZONES["downstairs"]["rooms"]["Main Bedroom"]
    temps[donor["temp"]] = donor_temp

    c = FakeController(temps, occ)
    if cooling_ended_min_ago is not None:
        c._cooling_ended_at = NOW - timedelta(minutes=cooling_ended_min_ago)
    return c


def run():
    target_cool = 73.0
    target_heat = 67.0
    results = []

    # Scenario 1: cooling stopped 2 min ago -> WET coil -> must NOT run blower.
    c = build(hot_room_temp=77.0, donor_temp=68.0, cooling_ended_min_ago=2)
    c._apply_fan_assist({}, "Auto", "idle", target_cool, target_heat)
    ok1 = (c._fan_mode != "on" and "on" not in c.fan_calls
           and any("coil-dry lockout" in m for m in c.logs))
    results.append(("wet coil (2m) suppresses blower", ok1))

    # Scenario 2: cooling stopped 10 min ago -> DRY coil -> SHOULD run blower.
    c = build(hot_room_temp=77.0, donor_temp=68.0, cooling_ended_min_ago=10)
    c._apply_fan_assist({}, "Auto", "idle", target_cool, target_heat)
    ok2 = (c._fan_mode == "on" and "on" in c.fan_calls)
    results.append(("dry coil (10m) allows blower", ok2))

    # Scenario 3: never cooled this run (_cooling_ended_at None) -> not gated.
    c = build(hot_room_temp=77.0, donor_temp=68.0, cooling_ended_min_ago=None)
    c._apply_fan_assist({}, "Auto", "idle", target_cool, target_heat)
    ok3 = (c._fan_mode == "on" and "on" in c.fan_calls)
    results.append(("no prior cooling -> not gated", ok3))

    # Scenario 4: heating direction must NEVER be gated even right after... well,
    # heating has no _cooling_ended_at normally, but prove the gate is cool-only:
    # cold room below heat setpoint, warm donor, cooling_ended 5m ago.
    temps, occ = {}, {}
    for zname, zone in svc.ZONES.items():
        for rname, s in zone["rooms"].items():
            temps[s["temp"]] = 70.0
            if s.get("occupancy"):
                occ[s["occupancy"]] = "off"
    cold = svc.ZONES["upstairs"]["rooms"]["Guest Bedroom 1"]
    temps[cold["temp"]] = 63.0          # below heat setpoint 67
    occ[cold["occupancy"]] = "on"
    warm = svc.ZONES["downstairs"]["rooms"]["Main Bedroom"]
    temps[warm["temp"]] = 72.0          # warmer donor
    c = FakeController(temps, occ)
    c._cooling_ended_at = NOW - timedelta(minutes=5)  # should be ignored: heating
    c._apply_fan_assist({}, "Auto", "idle", target_cool, target_heat)
    ok4 = (c._fan_mode == "on" and not any("coil-dry" in m for m in c.logs))
    results.append(("heating direction never gated", ok4))

    # Scenario 5: lockout boundary exactly at FAN_ASSIST_COIL_DRY_MIN -> dry
    # (>= threshold passes).
    c = build(hot_room_temp=77.0, donor_temp=68.0,
              cooling_ended_min_ago=svc.FAN_ASSIST_COIL_DRY_MIN)
    c._apply_fan_assist({}, "Auto", "idle", target_cool, target_heat)
    ok5 = (c._fan_mode == "on")
    results.append((f"boundary {svc.FAN_ASSIST_COIL_DRY_MIN:.0f}m allows blower", ok5))

    print("=== Dry-coil lockout unit test ===")
    allok = True
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        allok = allok and ok
    print("RESULT:", "ALL PASS" if allok else "FAILURES PRESENT")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    run()
