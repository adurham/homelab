"""Guard test: SETPOINT_NUDGE_ENABLED must default to False in production.

Added 2026-09-02 after the "freezing Living Room/Kitchen" incident: on this
house's ecobee, which controls to the AVERAGE of 14 room sensors, moving the
whole-house setpoint to force one chronically-hot room's compressor to escalate
drags every OTHER (well-behaved) room colder too -- it does not "stage harder
for a fixed target", it moves the target. See the smart-vent-controller skill
for the full incident writeup and the independent Opus review that confirmed
it. The mechanism's state machine is still tested in isolation (with the flag
force-enabled) by test_setpoint_nudge.py / test_nudge_*.py -- this is the one
guard that verifies the SHIPPED default is actually off, so a future edit
can't silently flip it back on without a test failing here first.

No pytest / appdaemon needed: same stub pattern as the other tests in tests/.
"""
import sys
import types

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

PASS = []
def check(name, cond):
    PASS.append(cond)
    print(("PASS" if cond else "FAIL"), "-", name)

check("SETPOINT_NUDGE_ENABLED defaults to False (production-shipped value)",
      svc.SETPOINT_NUDGE_ENABLED is False)

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
