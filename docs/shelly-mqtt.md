# Shelly Gen3 fleet — local MQTT architecture

All 6 Shelly Gen3 devices (pool, water-heater circulator, basement exhaust, 3
garage bays) use a **local-MQTT-first** architecture as of 2026-07-15. Shelly
cloud is disabled on every device. Home Assistant (via HA Cloud / Nabu Casa)
is the single remote-access path; the Shelly cloud dependency is cut.

## Why

On 2026-07-15 the pool Shelly's HTTP task wedged while its network stack stayed
alive — ping worked but every HTTP endpoint hung. The Shelly app and HA showed
the device offline/unavailable; Google Home (which only checks reachability)
still said online. The only recovery was a soft reboot via the local RPC API
(`Shelly.Reboot`, not `Sys.Reboot` which 403s), and the device thermal-crash-
looped because each reboot generates heat it couldn't shed in its enclosure.

MQTT is a separate task from HTTP on the device. With MQTT configured, a
wedged HTTP task does not mean loss of control — RPC-over-MQTT still works
(reboot, read state, toggle relays). Confirmed bidirectional 2026-07-15:
`Switch.GetStatus` published to `<device>/rpc` returned the relay state on the
`<src>/rpc` response topic.

## What it does

- **Mosquitto broker**: the HA `core_mosquitto` add-on on the HA host
  (`192.168.86.2:1883`). A dedicated `shelly` broker login (separate from the
  existing `frigate` and `homeassistant` logins) is used by all 6 devices.
- **Per-device MQTT config**: `Mqtt.SetConfig` with `enable`, `server`,
  `user:"shelly"`, `pass`, `topic_prefix` = device id, `rpc_ntf`, `status_ntf`,
  `enable_rpc`, `enable_control` all true. The password field is **`pass`**,
  NOT `password` (Shelly Gen3 docs require `pass`; sending `password` silently
  drops it and the broker logs "received null username or password").
- **Shelly cloud disabled**: `Cloud.SetConfig` with `enable:false` on every
  device. Applies immediately (`restart_required:false`).
- **HA integration unchanged**: the HA Shelly integration uses CoAP/mDNS for
  entity discovery, not MQTT — so MQTT enables the second control plane
  without changing how HA sees the devices day-to-day.

## Devices

| IP | Device | Model | Entity (HA switch) |
|----|--------|-------|---------------------|
| 192.168.86.8 | Pool pump | S3SW-001X8EU (1 Mini Gen3) | `switch.shelly1minig3_28372f21c5b8` |
| 192.168.86.24 | Water heater circulator | S3SW-001X8EU | `switch.shelly1minig3_28372f21c1dc` |
| 192.168.86.42 | Basement exhaust fan | S3SW-001P8EU (1PM Mini Gen3) | `switch.basement_exhaust_fan` |
| 192.168.86.43 | Right garage bay | S3SW-001X8EU | `cover.right_garage_bay_door` |
| 192.168.86.44 | Middle garage bay | S3SW-001X8EU | `cover.middle_garage_bay_door` |
| 192.168.86.45 | Left garage bay | S3SW-001X8EU | `cover.left_garage_door` |

The 3 garage devices are covers (`device_class: garage`, momentary relay:
`in_mode: detached`, `auto_off: true`, `auto_off_delay: 1.0s`) with
open/closed sensors (`binary_sensor.<left|middle|right>_garage_bay_garage_door`).

## Secrets

`shelly_mqtt_password` is a vault var in
`ansible/inventory/group_vars/all.yml` (mirrors the existing
`frigate_mqtt_password` pattern). Decrypt:

```
ansible localhost -i ansible/inventory/hosts --vault-password-file .vault_pass \
  -m debug -a "var=shelly_mqtt_password"
```

## Not managed here

- **Firmware**: all 6 on 1.7.5, the latest stable as of 2026-07-15
  (`Shelly.CheckForUpdate` lists only beta 2.0.0-beta3, no stable). Do not push
  the beta for stability — no cloud rollback path. Firmware updates are manual
  per-device when a new stable ships.
- **Pool pump thermal placement**: the pool Shelly runs hot (137-162°F in an
  83°F ambient, rated 40°C) because it's in a tight electrical box with the
  contactor and pump motor. The box can't be modified. Software levers
  (don't crash-loop a hot device, MQTT backstop) are in place; physical
  cooling is not. Temperature sensors on all 6 devices were enabled in HA
  2026-07-15 to log correlation data for any future schedule tuning.

## Operations

- **Reboot a wedged device** (HTTP up): `POST /rpc/Shelly.Reboot` to the
  device IP. Do NOT run a tight retry loop on a device over ~55°C — reboots
  generate heat and the thermal death spiral is worse than the wedge.
- **Reboot a wedged device** (HTTP down, MQTT up): publish
  `{"id":1,"src":"hermes","method":"Shelly.Reboot"}` to `<device-id>/rpc`.
  Response arrives on `hermes/rpc`.
- **Command via MQTT**: publish RPC to `<device-id>/rpc`, set `src` to a
  unique client id, subscribe to `<src>/rpc` for the response.
- **Add a new Shelly**: create a `shelly` login on the broker (already done —
  the single `shelly` user is shared), then `Mqtt.SetConfig` on the device
  with the config above and `Cloud.SetConfig enable:false`.

## See also

- Hermes skill `shelly-gen3-recovery` — full diagnosis, reboot methods, thermal
  crash-loop details, mosquitto add-on user management via the HA websocket
  API, and the exact RPC call shapes.