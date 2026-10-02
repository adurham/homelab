# Homelab Integration Map

## 🏠 Integrated Devices

| Device | Integration | IP Address | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **HPWH** | Rheem EcoNet | `192.168.86.x` | ✅ Optimized | Logic: 35% enter, 60% exit High Demand. |
| **Circ. Pump** | Shelly | `192.168.86.24`| ✅ Aligned | Water-heater circulator. Cooldown: 30 minutes. |
| **Pool Pump** | Shelly | `192.168.86.8`| ✅ Mapped | Shelly 1 Mini G3. |
| **Garage (Left)**| Shelly | `192.168.86.45`| ✅ Mapped | Shelly relay control (`cover.left_garage_door`). |
| **Garage (Mid)** | Shelly | `192.168.86.44`| ✅ Mapped | Shelly relay control (`cover.middle_garage_bay_door`). |
| **Living Room TV**| Sony Bravia | `192.168.86.195`| ✅ REST API | Optimized for performance. |
| **PS5** | Hue Sync Box | `192.168.86.x` | ✅ Intelligent | Restores previous scene/state on power off. |
| **Nest Doorbell**| Nest SDM | `192.168.86.28`| ✅ Active | Real-time chime and motion events. |
| **Nest Protects**| HACS (Nest) | `192.168.86.x` | ✅ Active | Living Room & Foyer units active. |
| **Ecobee Sensors**| HomeKit/Cloud| `192.168.86.x` | ✅ Active | 12 room-level occupancy sensors. |
| **Network Security**| AdGuard Home| `192.168.86.2` | ✅ Configured | Add-on active on UDP 53. DoT Upstreams. |

## 🌐 Network Inventory (192.168.86.x)

| IP Range | Category | Count | Primary Devices |
| :--- | :--- | :--- | :--- |
| `.1 - .2` | Core Infra | 2 | Nest Wifi Pro Gateway, Home Assistant |
| `.11 - .13` | Lab Cluster | 3 | Proxmox Nodes (Apple M4 Max Hardware) |
| `.22 - .196` | Climate | 8+ | Flair Vents & Bridge, Ecobee Remote Sensors |
| `.28 - .63` | Nest/Google | 4+ | Cameras, Displays, Doorbells |
| `.38 - .198` | Smart Power | 5+ | Shelly Pumps, Wyze Plugs, IoT |
| `.52 - .195` | Media | 3+ | Sony Bravia, Samsung Displays |
| `.105` | Workstation | 1 | MacBook Pro — STALE: the laptop's live LAN IP is `192.168.86.46` (DHCP; verified 2026-10-02). |

> **Verify against current sources:** `docs/shelly-mqtt.md` is the authoritative
> live IP map for the Shelly fleet, and `docs/ipam.md` for cluster/LAN
> allocations. This file (last substantive edit 2026-03-07) had drifted — the
> Shelly rows above were corrected 2026-10-02. Entries still marked `86.x`
> (HPWH, PS5/Hue Sync, Nest Protects, Ecobee, Nest Doorbell) are unresolved.

## 📊 Data Collection Summary

- **House Temperature Delta:** Difference between hottest and coldest room.
- **House Average Temp:** Whole-house thermal average.
- **AdGuard Metrics:** DNS query and block rates flowing to VictoriaMetrics.
- **DNS Performance:** Quad9 (17ms), Cloudflare (20ms).
- **TTL Optimization:** Global minimum TTL set to 3600.

## 🛡️ Safety & Reliability

- **Emergency Safety:** ⚠️ SUPERSEDED — `safety_smoke_co_emergency` was removed 2026-05-30 (it triggered off Nest Protect entities the SDM API doesn't expose, so it could never fire). The Nest Protects still alarm standalone; an HA-native smoke/CO automation would need a Z-Wave/Zigbee detector.
- **DNS Watchdog:** `infrastructure_adguard_watchdog`. Auto-restarts AdGuard.
- **Laundry Monitor:** Robust state-based template (survives HA restarts).
- **House Occupancy:** Combined binary sensor for all 14+ occupancy sources.
