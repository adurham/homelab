"""Offline unit test for the debounced manual-override detection.

Stubs appdaemon.plugins.hass.hassapi so smart_vent_controller imports without
AppDaemon installed, then subclasses the controller with a fake HA state map
and a scriptable run_in that we can fire manually (no real event loop).

Reproduces the 2026-07-23 bug: 8 vents were simultaneously flagged "manual
override" within 1.5s of a bulk close command -- physically impossible for 8
people to touch 8 vents at once. The cause: on_vent_manual_change latched the
60-minute hold on the FIRST tilt-position mismatch, which fires on a Flair
vent's own in-flight transient reading while it's still traveling toward the
position WE just commanded. Fixed by deferring the hold to a confirmation
check MANUAL_OVERRIDE_CONFIRM_SEC later, which only fires if the position
still disagrees with what we last commanded.
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

NOW = datetime(2026, 7, 23, 5, 1, 49)


class FakeController(svc.SmartVentController):
    """Controller with a scriptable current-position map and a fake run_in
    that just records the (callback, delay, kwargs) tuple instead of actually
    scheduling -- the test fires it manually to simulate the delay elapsing.
    """

    def __init__(self):
        self._manual_holds = {}
        self._last_positions = {}
        self._current_tilt = {}   # entity -> current_tilt_position
        self.scheduled = []       # list of (callback, delay, kwargs)
        self.logs = []

    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def get_state(self, entity, attribute=None):
        if attribute == "current_tilt_position":
            return self._current_tilt.get(entity)
        return None

    def run_in(self, callback, delay, **kwargs):
        self.scheduled.append((callback, delay, kwargs))

    def fire_all_scheduled(self):
        pending = self.scheduled
        self.scheduled = []
        for callback, delay, kwargs in pending:
            callback(kwargs)


def run():
    results = []

    # Scenario 1 (the actual bug): we command a vent closed (0%), the Flair
    # device reports a transient in-flight value while still traveling, then
    # settles to our commanded value a moment later. Must NOT latch a hold.
    c = FakeController()
    entity = "cover.hallway_907e_vent_2"
    c._last_positions[entity] = 0          # we just commanded 0%
    c._current_tilt[entity] = 45           # device mid-travel, reports 45%
    c.on_vent_manual_change(entity, "current_tilt_position", 100, 45, {})
    # No immediate hold -- must be deferred.
    ok1 = entity not in c._manual_holds
    results.append(("no immediate hold on in-flight mismatch", ok1))

    # Device settles to our commanded value before the confirm delay fires.
    c._current_tilt[entity] = 0
    c.fire_all_scheduled()
    ok2 = entity not in c._manual_holds
    results.append(("settled-to-commanded value -> no hold applied", ok2))

    # Scenario 2: genuine manual override -- device settles to something
    # OTHER than what we commanded (a human actually moved it) and stays
    # there past the confirm delay. Hold MUST be applied.
    c = FakeController()
    entity2 = "cover.living_room_fc56_vent_2"
    c._last_positions[entity2] = 0          # we commanded 0%
    c._current_tilt[entity2] = 100          # user opened it instead
    c.on_vent_manual_change(entity2, "current_tilt_position", 0, 100, {})
    ok3 = entity2 not in c._manual_holds     # still deferred at fire time
    c.fire_all_scheduled()
    ok3 = ok3 and entity2 in c._manual_holds
    results.append(("genuine override still disagreeing -> hold applied", ok3))

    # Scenario 3: bulk close of 8 vents within 1.5s (the exact reported bug
    # shape) -- all 8 report a transient mismatch, then all settle to 0%.
    # None should end up holding.
    c = FakeController()
    bulk_entities = [f"cover.room{i}_vent" for i in range(8)]
    for e in bulk_entities:
        c._last_positions[e] = 0
        c._current_tilt[e] = 50   # transient in-flight reading
        c.on_vent_manual_change(e, "current_tilt_position", 100, 50, {})
    for e in bulk_entities:
        c._current_tilt[e] = 0    # settles to commanded value
    c.fire_all_scheduled()
    ok4 = all(e not in c._manual_holds for e in bulk_entities)
    results.append(("bulk close of 8 vents -> zero false holds", ok4))

    print("=== Manual-override debounce unit test ===")
    allok = True
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        allok = allok and ok
    print("RESULT:", "ALL PASS" if allok else "FAILURES PRESENT")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    run()
