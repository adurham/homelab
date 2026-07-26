"""Offline unit test for the debounced manual-override detection.

Stubs appdaemon.plugins.hass.hassapi so smart_vent_controller imports without
AppDaemon installed, then subclasses the controller with a fake HA state map
and a scriptable run_in that we can fire manually (no real event loop).

Reproduces two real production incidents (2026-07-23):

1. 8 vents were simultaneously flagged "manual override" within 1.5s of a
   bulk close command -- physically impossible for 8 people to touch 8 vents
   at once. Cause: on_vent_manual_change latched the 60-minute hold on the
   FIRST tilt-position mismatch, which fires on a Flair vent's own in-flight
   transient reading while it's still traveling toward the position WE just
   commanded.

2. After adding a SINGLE confirm-and-recheck (first fix attempt), a vent
   commanded to 0% was observed cycling 0 -> 100 -> 0 across a ~15s window
   with no human or code touching it (the Flair cloud coordinator itself
   flapped, not just motor travel time) -- long enough to still be
   disagreeing at the single recheck point, producing a false hold anyway.
   Cause: one recheck isn't enough when the noise source can outlast the
   confirm delay. Fixed with a STABLE double-confirmation: a second recheck
   must find the SAME disagreeing value as the first recheck (i.e. it has
   actually stopped moving) before a hold is latched.
"""
import sys
import types
from datetime import datetime

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
    scheduling -- the test drains it wave-by-wave to simulate real time
    passing, so a callback that itself calls run_in() (the check=1 -> check=2
    chain) gets its own follow-up processed on the NEXT drain, exactly like a
    real event loop would.
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

    def drain_one_wave(self):
        """Fire everything currently queued exactly once. Any run_in() calls
        made BY those callbacks land in a fresh queue for the next wave."""
        pending = self.scheduled
        self.scheduled = []
        for callback, _delay, kwargs in pending:
            callback(kwargs)

    def drain_all(self, max_waves=10):
        for _ in range(max_waves):
            if not self.scheduled:
                return
            self.drain_one_wave()


def run():
    results = []

    # Scenario 1 (the original bug): we command a vent closed (0%), the
    # Flair device reports a transient in-flight value while still
    # traveling, then settles to our commanded value before the first
    # recheck. Must NOT latch a hold.
    c = FakeController()
    entity = "cover.hallway_907e_vent_2"
    c._last_positions[entity] = 0          # we just commanded 0%
    c._current_tilt[entity] = 45           # device mid-travel, reports 45%
    c.on_vent_manual_change(entity, "current_tilt_position", 100, 45, {})
    # No immediate hold -- must be deferred.
    ok1 = entity not in c._manual_holds
    results.append(("no immediate hold on in-flight mismatch", ok1))

    # Device settles to our commanded value before the first recheck fires.
    c._current_tilt[entity] = 0
    c.drain_all()
    ok2 = entity not in c._manual_holds
    results.append(("settled-to-commanded value at 1st recheck -> no hold", ok2))

    # Scenario 2 (the real-world flap that broke a single-recheck fix): the
    # coordinator reports 0 -> 100 -> 0 with neither value being stable
    # across both rechecks. Must NOT latch a hold (still noise, just
    # slower-resolving noise than scenario 1).
    c = FakeController()
    entity_flap = "cover.living_room_5d8e_vent_2"
    c._last_positions[entity_flap] = 0     # we commanded 0%
    c._current_tilt[entity_flap] = 0       # initial mismatch trigger (e.g. attribute momentarily unset elsewhere)
    c.on_vent_manual_change(entity_flap, "current_tilt_position", 100, 0, {})
    # First recheck: coordinator now reports 100 (still disagreeing) -- this
    # schedules a second recheck.
    c._current_tilt[entity_flap] = 100
    c.drain_one_wave()
    ok3 = entity_flap not in c._manual_holds
    # Second recheck: coordinator flapped AGAIN, now reporting 0 -- disagrees
    # with the first-recheck value (100), so still not trusted as stable.
    c._current_tilt[entity_flap] = 0
    c.drain_one_wave()
    ok3 = ok3 and entity_flap not in c._manual_holds
    results.append(("flapping coordinator reading -> never latches", ok3))

    # Scenario 3: genuine manual override -- device settles to something
    # OTHER than what we commanded (a human actually moved it) and STAYS
    # there across both rechecks. Hold MUST be applied.
    c = FakeController()
    entity2 = "cover.living_room_fc56_vent_2"
    c._last_positions[entity2] = 0          # we commanded 0%
    c._current_tilt[entity2] = 100          # user opened it instead
    c.on_vent_manual_change(entity2, "current_tilt_position", 0, 100, {})
    ok4 = entity2 not in c._manual_holds     # still deferred right after the event
    c.drain_all()                            # both rechecks see the same 100% -> latch
    ok4 = ok4 and entity2 in c._manual_holds
    results.append(("genuine override stable across both rechecks -> hold applied", ok4))

    # Scenario 4: bulk close of 8 vents within 1.5s (the exact reported bug
    # shape) -- all 8 report a transient mismatch, then all settle to 0%
    # before either recheck. None should end up holding.
    c = FakeController()
    bulk_entities = [f"cover.room{i}_vent" for i in range(8)]
    for e in bulk_entities:
        c._last_positions[e] = 0
        c._current_tilt[e] = 50   # transient in-flight reading
        c.on_vent_manual_change(e, "current_tilt_position", 100, 50, {})
    for e in bulk_entities:
        c._current_tilt[e] = 0    # settles to commanded value
    c.drain_all()
    ok5 = all(e not in c._manual_holds for e in bulk_entities)
    results.append(("bulk close of 8 vents -> zero false holds", ok5))

    print("=== Manual-override debounce unit test ===")
    allok = True
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        allok = allok and ok
    print("RESULT:", "ALL PASS" if allok else "FAILURES PRESENT")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    run()
