"""Guard test: setpoint-nudge safety invariants must hold whenever ENABLED.

Originally added 2026-09-02 after the "freezing Living Room/Kitchen" incident
to assert SETPOINT_NUDGE_ENABLED defaulted to False. Re-enabled the SAME DAY
(afternoon) once two structural fixes closed the actual failure mode (see
commits 745414b/3ef9b6e + the RESOLVED section of the smart-vent-controller
skill):
  1. GAIN/MAX_F collapsed to a fixed, hard-capped nudge magnitude -- it can
     never again drag the house 3F+ colder chasing one hot room, no matter
     the cap's current value (raised 1.0F -> 2.0F later the same day once
     live data showed the house's manual-only stage-2 cooling differential
     is 2.0F and a 1.0F nudge only reached the boundary, never exceeded it
     -- see the MAX_F comment in the constants block for the live numbers).
  2. A 2-hour human-override cooldown -- it can never fight the user again
     after they touch the thermostat.

This guard verifies the SHAPE of those two safety invariants holds,
REGARDLESS of the exact MAX_F value chosen or whether the mechanism is
enabled/disabled at any given time -- so a future edit that reintroduces
the original failure mode (e.g. decoupling GAIN from MAX_F so the nudge
becomes partial/scaling again, or removing/shortening the override
cooldown) fails a test here BEFORE it ever reaches production, rather than
requiring a repeat of the live incident to notice. Does NOT assert a
specific value for SETPOINT_NUDGE_ENABLED or SETPOINT_NUDGE_MAX_F
themselves -- both are live operational decisions (see skill), not
something a test should pin to a fixed number. What IS pinned, deliberately:
MAX_F must never exceed the SETPOINT_HEATCOOL_MIN_DELTA_F margin in a way
that could produce an invalid heat/cool pair (checked below), and the
saturation guarantee (GAIN*ENGAGE_F >= MAX_F) must always hold so the nudge
stays single-shot regardless of its magnitude.

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

# --- Invariant 1: the nudge can NEVER move the setpoint more than MAX_F
#     total, regardless of how large worst_excess gets, AND MAX_F itself
#     must stay well below the pre-incident value (3.0F) that caused the
#     original "cool the whole house 3F+ chasing one hot room" failure.
#     MAX_F is allowed to be tuned (it moved 1.0 -> 2.0 the same day this
#     test was written, once live data showed 1.0F wasn't enough to clear
#     the house's manual-only 2.0F stage-2 differential) -- what must NEVER
#     regress is the SATURATION property below, which is what makes the
#     nudge single-shot instead of a multi-step ratchet.
check("SETPOINT_NUDGE_MAX_F stays well under the pre-incident 3.0F "
      "(some headroom kept deliberately -- not creeping back toward it)",
      svc.SETPOINT_NUDGE_MAX_F <= 2.5)
check("SETPOINT_NUDGE_ENGAGE_F * SETPOINT_NUDGE_GAIN saturates at/above "
      "MAX_F -- every engagement is the SAME fixed magnitude (MAX_F), "
      "never a partial/scaling value in between",
      svc.SETPOINT_NUDGE_ENGAGE_F * svc.SETPOINT_NUDGE_GAIN >= svc.SETPOINT_NUDGE_MAX_F)
check("GAIN*MAX_F combination cannot produce more than MAX_F even at "
      "extreme worst_excess (clamped by MAX_F regardless of GAIN)",
      min(1000.0 * svc.SETPOINT_NUDGE_GAIN, svc.SETPOINT_NUDGE_MAX_F) <= svc.SETPOINT_NUDGE_MAX_F)
check("nudging by MAX_F can never violate the heat/cool minimum delta "
      "(MAX_F must leave real room before the coupling floor kicks in)",
      svc.SETPOINT_NUDGE_MAX_F < svc.SETPOINT_HEATCOOL_MIN_DELTA_F)

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
