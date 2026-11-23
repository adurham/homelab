"""Offline test: the recirculation gate in front of the comfort nudge.

The owner's rule is "only nudge the thermostat if recirculating the current air
is not sufficient". That is measured from FAN-ASSIST's own outcome — the attempt
it recorded for the room, how long ago, and whether the gap has closed since —
not from the delivery penalty (which only accrues mid-call, when a nudge is a
no-op, and opens for duct-limited rooms where extra runtime buys nothing).

Nothing in this gate writes a setpoint: the comfort source is still pinned off
and the decision is published in shadow on sensor.smart_vent_scorecard.
"""
import os
import sys
import types
from datetime import datetime, timedelta

ad = types.ModuleType("appdaemon")
plugins = types.ModuleType("appdaemon.plugins")
hassmod = types.ModuleType("appdaemon.plugins.hass")
hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")


class _Hass:
    def __init__(self, *a, **k):
        pass


hassapi.Hass = _Hass
sys.modules["appdaemon"] = ad
sys.modules["appdaemon.plugins"] = plugins
sys.modules["appdaemon.plugins.hass"] = hassmod
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi

_APPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps")
if not os.path.isdir(_APPS):
    _APPS = "/home/adam.durham/repos/homelab/homeassistant/appdaemon/apps"
sys.path.insert(0, _APPS)
import smart_vent_controller as svc  # noqa: E402

NOW = datetime(2026, 11, 23, 20, 0, 0)
PASS = []


def check(name, ok):
    PASS.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}")


class Fake(svc.SmartVentController):
    def __init__(self, attempts=None):
        self._recirc_attempt = attempts or {}
        self.logs = []

    def log(self, msg, *a, **k):
        self.logs.append(msg)

    def datetime(self, aware=False):
        return NOW


KEY = ("upstairs", "Game Room")


def attempt(mins_ago, gap):
    return {KEY: {"since": NOW - timedelta(minutes=mins_ago), "gap": gap}}


# =============================================================================
# 1. Truth table.
# =============================================================================
check("T1 a room fan-assist never tried is NOT eligible (silence is not failure)",
      Fake({})._recirc_exhausted(KEY, 3.0) is False)
check("T1 an attempt younger than the dwell is NOT eligible",
      Fake(attempt(5, 3.0))._recirc_exhausted(KEY, 3.0) is False)
check("T1 an old attempt with the gap unchanged IS eligible",
      Fake(attempt(30, 3.0))._recirc_exhausted(KEY, 3.0) is True)
check("T1 an old attempt where the gap has closed enough is NOT eligible",
      Fake(attempt(30, 3.0))._recirc_exhausted(KEY, 2.0) is False)
check("T1 a small improvement inside the gain still counts as stuck",
      Fake(attempt(30, 3.0))._recirc_exhausted(KEY, 2.7) is True)
check("T1 exactly at the dwell boundary is eligible",
      Fake(attempt(svc.SETPOINT_NUDGE_RECIRC_MIN, 3.0))._recirc_exhausted(KEY, 3.0) is True)
check("T1 a room at or past target is never eligible",
      Fake(attempt(30, 3.0))._recirc_exhausted(KEY, 0.0) is False)

# A recovered room drops its evidence, so an old attempt cannot keep it eligible
# through the rest of the day.
ha = Fake(attempt(90, 4.0))
check("T1 recovering to target clears the stored attempt",
      ha._recirc_exhausted(KEY, -0.5) is False and KEY not in ha._recirc_attempt)
check("T1 after clearing, becoming cold again is not immediately eligible",
      ha._recirc_exhausted(KEY, 3.0) is False)

# =============================================================================
# 2. Recording, and the shape the shadow publish expects.
# =============================================================================
ha = Fake({})
ha._record_recirc_attempt(KEY, 2.5)
check("T2 recording stamps the current time and the gap",
      ha._recirc_attempt[KEY]["gap"] == 2.5
      and ha._recirc_attempt[KEY]["since"] == NOW)
check("T2 a fresh record is not yet eligible",
      ha._recirc_exhausted(KEY, 2.5) is False)

# =============================================================================
# 3. The source stays off in production: this gate must not have turned it on.
# =============================================================================
check("T3 the comfort source is still pinned off in the controller source",
      svc.SETPOINT_NUDGE_COMFORT_ENABLED is False)
check("T3 v1 caps the comfort nudge tighter than pre-cool",
      svc.SETPOINT_NUDGE_COMFORT_MAX_F < svc.SETPOINT_NUDGE_MAX_F)

print(f"\n{sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
