"""Guard test: setpoint-nudge safety invariants must hold whenever ENABLED.

Originally added 2026-09-02 after the "freezing Living Room/Kitchen" incident
to assert SETPOINT_NUDGE_ENABLED defaulted to False. Re-enabled the SAME DAY
(afternoon) once two structural fixes closed the actual failure mode (see
commits 745414b/3ef9b6e + the RESOLVED section of the smart-vent-controller
skill):
  1. GAIN/MAX_F collapsed to a fixed, hard-capped 1.0F nudge -- it can never
     again drag the house 3F+ colder chasing one hot room.
  2. A 2-hour human-override cooldown -- it can never fight the user again
     after they touch the thermostat.

This guard now verifies those two safety invariants hold, REGARDLESS of
whether the mechanism is enabled or disabled at any given time -- so a
future edit that reintroduces the original failure mode (e.g. bumping
MAX_F back up, or removing/shortening the override cooldown) fails a test
here BEFORE it ever reaches production, rather than requiring a repeat of
the live incident to notice. Does NOT assert a specific value for
SETPOINT_NUDGE_ENABLED itself -- that's a live operational decision (see
skill), not something a test should pin.

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

# --- Invariant 1: the nudge can NEVER move the setpoint more than 1F total,
#     regardless of how large worst_excess gets. This is what makes the
#     "cool the whole house to 70 to chase one hot room" failure mode
#     structurally impossible rather than just discouraged.
check("SETPOINT_NUDGE_MAX_F is hard-capped at 1.0F (was 3.0F pre-incident)",
      svc.SETPOINT_NUDGE_MAX_F <= 1.0)
check("SETPOINT_NUDGE_ENGAGE_F already exceeds MAX_F -- every engagement is "
      "the SAME fixed magnitude, never partial/scaling",
      svc.SETPOINT_NUDGE_ENGAGE_F >= svc.SETPOINT_NUDGE_MAX_F)
check("GAIN*MAX_F combination cannot produce >1F even at extreme worst_excess "
      "(clamped by MAX_F regardless of GAIN)",
      min(1000.0 * svc.SETPOINT_NUDGE_GAIN, svc.SETPOINT_NUDGE_MAX_F) <= 1.0)

# --- Invariant 2: a detected human override must impose a REAL cooldown
#     (not a token few-minute delay) before any new nudge can engage --
#     this is what stops the mechanism from fighting the user back.
check("SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN exists and is a real window "
      "(>=60 min, not a token few-minute delay)",
      getattr(svc, "SETPOINT_NUDGE_OVERRIDE_COOLDOWN_MIN", 0) >= 60)

# --- Sanity: the disable flag itself must still exist as a real kill switch,
#     whatever its current value -- a future refactor must not delete it.
check("SETPOINT_NUDGE_ENABLED exists as a boolean kill switch",
      isinstance(svc.SETPOINT_NUDGE_ENABLED, bool))

print()
print(f"RESULT: {sum(PASS)}/{len(PASS)} checks passed")
sys.exit(0 if all(PASS) else 1)
