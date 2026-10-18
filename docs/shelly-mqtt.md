# Shelly fleet — cloud off, local MQTT, Matter into HA

All 7 Shelly devices (6 Gen3 + the Gen4 workstation plug) run with **Shelly
cloud disabled**, **local MQTT to the HA broker**, and **Matter enabled and
commissioned into Home Assistant**. HA is the only Matter controller and the
only path to Google Home — nothing is paired directly to Google/Apple/Alexa.

Verified live 2026-10-18 (not taken from earlier notes).

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

Matter (2026-10-18) adds a second local control path inside HA, independent of
both the Shelly integration (CoAP) and MQTT. All three terminate at HA.

## What it does

- **Mosquitto broker**: the HA `core_mosquitto` add-on on the HA host
  (`192.168.86.2:1883`). A dedicated `shelly` broker login (separate from the
  existing `frigate` and `homeassistant` logins) is used by all 7 devices.
- **Per-device MQTT config**: `Mqtt.SetConfig` with `enable`, `server`,
  `user:"shelly"`, `pass`, `topic_prefix` = device id, `rpc_ntf`, `status_ntf`,
  `enable_rpc`, `enable_control` all true. The password field is **`pass`**,
  NOT `password` (Shelly Gen3 docs require `pass`; sending `password` silently
  drops it and the broker logs "received null username or password").
- **Shelly cloud disabled**: `Cloud.SetConfig` with `enable:false` on every
  device (all 7 report `Cloud.GetStatus connected:false`).
- **Matter**: `Matter.SetConfig enable:true`, reboot, then
  `Matter.GetSetupCode` → HA websocket `matter/commission` with the manual
  code. All 7 report `num_fabrics:1`. HA's Matter integration (entry
  `01JZBDH6EE15S07KJA8R5YDBB0`) creates a second switch entity per device.
- **HA integrations unchanged**: the HA Shelly integration still uses
  CoAP/mDNS for its own entities. MQTT and Matter are additional paths, not
  replacements.

## Devices (state 2026-10-18)

| Device | Shelly id | MAC | IP (2026-10-18) | HA (Shelly integration) |
|--------|-----------|-----|--------------|--------------------------|
| Pool pump | shelly1minig3-28372f21c5b8 | 28:37:2F:21:C5:B8 | 192.168.86.25 | `switch.shelly1minig3_28372f21c5b8` |
| Water heater circulator | shelly1minig3-28372f21c1dc | 28:37:2F:21:C1:DC | 192.168.86.222 | `switch.shelly1minig3_28372f21c1dc` |
| Basement exhaust fan | shelly1pmminig3-d0cf13cbfc28 | D0:CF:13:CB:FC:28 | 192.168.86.24 | `switch.basement_exhaust_fan` |
| Right garage bay | shelly1minig3-b08184ee0fd0 | B0:81:84:EE:0F:D0 | 192.168.86.211 | `cover.right_garage_bay_door` |
| Middle garage bay | shelly1minig3-34b7dac55ea4 | 34:B7:DA:C5:5E:A4 | 192.168.86.21 | `cover.middle_garage_bay_door` |
| Left garage bay | shelly1minig3-34b7dac49574 | 34:B7:DA:C4:95:74 | 192.168.86.216 | `cover.left_garage_door` |
| amd-workstation plug | shellyplugusg4-e8f60a7e1528 | E8:F6:0A:7E:15:28 | 192.168.86.57 | `switch.amd_workstation` |

The 3 garage devices are covers (`device_class: garage`, momentary relay:
`in_mode: detached`, `auto_off: true`, `auto_off_delay: 1.0s`) with
open/closed sensors (`binary_sensor.<left|middle|right>_garage_bay_garage_door`).
The plug is a Shelly Plug US Gen4 (S4PL-00116US), `initial_state: on`.

**Addressing.** The earlier IPs (.8/.24/.42/.43/.44/.45) are dead — everything
drifted into the Nest DHCP pool (.20-.250). All 7 devices are DHCP with **DHCP
reservations set in the Google Home app** (2026-10-18), so the addresses below
are now sticky. Reservation names match the device names: `Shelly Pool Pump` .25,
`Shelly Circulator Pump` .222, `Shelly Exhaust Fan` .24, `Shelly Right Garage Bay
Door` .211, `Shelly Middle Garage Bay Door` .21, `Shelly Left Garage Bay Door`
.216, `Shelly Workstation Plug` .57. If a reservation is ever changed, HA's
Shelly integration follows the IP by itself (zeroconf) and MQTT/Matter are
IP-agnostic — but `homeassistant/command_line.yaml` hardcodes the workstation
plug's `.57`, so that one must not move without a config deploy.

## Security status (important)

- **Cloud**: off on all 7. No vendor cloud, no Shelly app control.
- **Remote path**: HA only (Nabu Casa).
- **Local surface is NOT HA-only.** All 7 report `auth_en:false` and serve
  unauthenticated HTTP RPC on port 80; `curl http://<ip>/rpc/Shelly.GetDeviceInfo`
  returns 200 from any LAN client, and the same endpoint accepts
  `Switch.Set`/`Cover.*`. Setting a device password (`Shelly.SetAuth`) blocks
  that, but CoAP (what the HA Shelly integration uses) stays open, so a password
  raises the bar rather than sealing it. True enforcement needs an IoT
  VLAN/SSID that can reach only HA — the Nest Wi-Fi cannot do that (guest
  network would cut HA off too).
- **Matter**: commissioned to HA only (`num_fabrics:1`). Any other controller
  would need the device's pairing code and physical access to the label.

## Reboot behavior

A Shelly reboot does **not** drop the relay. Verified 2026-10-18 with the
basement exhaust fan running (33 W): during the reboot HTTP was down for ~2 s,
the fan never lost power, and the relay came back `output:true`. The Gen4
workstation plug rebooted itself to apply its MQTT config while the workstation
was running — power was uninterrupted.

Still, prefer rebooting when the load is idle (pool pump off, workstation
idle). `Shelly.Reboot` is the soft reboot; `Sys.Reboot` 403s.

## Secrets

`shelly_mqtt_password` is a vault var in
`ansible/inventory/group_vars/all.yml` (mirrors the existing
`frigate_mqtt_password` pattern). Decrypt:

```
ansible localhost -i ansible/inventory/hosts --vault-password-file .vault_pass \
  -m debug -a "var=shelly_mqtt_password"
```

## Operations

- **Reboot a wedged device** (HTTP up): `POST /rpc/Shelly.Reboot` to the
  device IP. Do NOT run a tight retry loop on a device over ~55°C — reboots
  generate heat and the thermal death spiral is worse than the wedge.
- **Reboot a wedged device** (HTTP down, MQTT up): publish
  `{"id":1,"src":"hermes","method":"Shelly.Reboot"}` to `<device-id>/rpc`.
  Response arrives on `<src>/rpc`.
- **Command via MQTT**: publish RPC to `<device-id>/rpc`, set `src` to a
  unique client id, subscribe to `<src>/rpc` for the response. The response
  carries `src` = device id, so key on `dst`/`id`, not `src`.
- **Add a new Shelly**: create a `shelly` login on the broker (already done —
  the single `shelly` user is shared), then `Mqtt.SetConfig` with the config
  above, `Cloud.SetConfig enable:false`, `Matter.SetConfig enable:true`, reboot,
  and commission with `Matter.GetSetupCode` → HA `matter/commission`. MQTT
  config changes need a reboot to take effect (`restart_required:true`).

## Firmware

- 5 Gen3 Minis: 2.0.1 (`20260923-075459`)
- Basement 1PM Gen3: 2.1.0 (`20261014-085741`)
- Workstation Plug Gen4: 2.0.1 (`20260923-075613`)

Beta 2.2.0-beta1 is offered by `Shelly.CheckForUpdate` on the Gen4. Do not push
beta firmware — no cloud rollback path. Manual per-device update when a new
stable ships.

## Not managed here

- **Pool pump thermal placement**: the pool Shelly runs hot (137-162°F in an
  83°F ambient, rated 40°C) because it's in a tight electrical box with the
  contactor and pump motor. The box can't be modified. Software levers are in
  place; physical cooling is not. Temperature sensors on all devices were
  enabled in HA 2026-07-15 to log correlation data for any future schedule
  tuning.

## See also

- Hermes skill `shelly-gen3-recovery` — full diagnosis, reboot methods, thermal
  crash-loop details, mosquitto add-on user management via the HA websocket
  API, and the exact RPC call shapes.
