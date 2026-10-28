# Shark2MQTT recovered — 2026-10-28

**What was wrong.** The `Shark2MQTT (production - water-flow-level fork)` app on the HA
Green sat in `state: error` with `boot: auto` and no logs at all: the container had
failed at some point after a boot, the Supervisor cleaned the dead container on the
next start attempt, and with it went the exit code. It never restarted itself because
its watchdog was off.

**What was done.**

1. Started it and watched it work — MQTT to `core-mosquitto:1883`, Skegox auth, one
   device (`CleanElizabeth2`, SND000001229736), HA discovery published.
2. Turned its watchdog on, so a death is now a restart instead of a silent hole. The
   rest of its options were left byte-identical (verified by hashing the options block
   before and after).
3. Restarted it once to prove the cold path: reconnects and republishes discovery
   within a second.

**Proof it works end to end.** 18 entities in HA, including
`select.cleanelizabeth2_water_flow_level` (the fork's contribution),
`button.cleanelizabeth2_clean_{kitchen,living_room,foyer}` from the Skegox room map,
and `binary_sensor.cleanelizabeth2_charging`. At 14:16 local,
`vacuum.cleanelizabeth2` = `docked`, battery 100 %, charging `on`.

**What is still unknown.** The exit code that caused the original error is gone — the
Supervisor's cleanup removed it before anyone looked. If it errors again, the useful
evidence is the Supervisor log line naming the code:

```
ha supervisor logs | grep <slug>
```

A crash loop after a HA reboot would point at the MQTT broker not being ready yet; that
is a guess, not a finding, and the watchdog covers it either way.

**Details worth remembering.** It is a **locally built** app
(`f5b120c9/aarch64-addon-shark2mqtt`, version `1.0.7-waterflow4`, `image: null` → built
on the Green, not pulled), so it needs a rebuild rather than an update when the fork
changes. Disk on the Green is at 73 % (7.3 GB free) — enough headroom for a rebuild,
but not for a from-source build that drags in a toolchain.

## The crash itself, fixed in the fork — 2026-10-28

The watchdog stops a death from going unnoticed; it does not stop the death. The death
was a cold-boot race in the wrapper: `run.sh` read the Mosquitto service details from
the Supervisor **once**, and if the app started before that service was registered the
read came back empty, the fallback had no `mqtt_host`, and the script exited 1 with no
retry.

Fixed in `adurham/shark2mqtt-addon` (`97f764f`, version `1.0.7-waterflow4`):

- `fetch_mqtt_service()` retries the lookup — 60 attempts, 2 s apart, both overridable
  via `MQTT_SERVICE_RETRIES` / `MQTT_SERVICE_RETRY_DELAY` — before falling back to
  manual settings.
- With genuinely no broker anywhere it exits non-zero and says why, so the watchdog has
  something to act on instead of a silent corpse.
- `CONFIG_PATH` is now overridable, which is what makes the wrapper testable off-box.
- `tests/test_run_sh_retry.sh` runs the real `run.sh` against a curl stub: broker ready,
  broker three attempts late, Supervisor dead with manual settings, nothing configured
  anywhere. 11 checks, all green. It also caught a bug in the fix — the progress line
  went to stdout, which is the channel carrying the captured JSON reply, and corrupted
  the parse.

Deployed the same day via `ha apps update` (the Supervisor's repo clone is the fork):
running `1.0.7-waterflow4`, watchdog on, discovery republished, `vacuum.cleanelizabeth2`
= `docked` at 100 %. Disk after the rebuild: 7.3 GB free (73 %).
