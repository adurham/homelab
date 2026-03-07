# Homelab Integration Map

## 🏠 Integrated Devices

| Device | Integration | IP Address | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **HPWH** | Rheem EcoNet | `192.168.86.x` | ✅ Optimized | Logic: 35% enter, 60% exit High Demand. |
| **Circ. Pump** | Shelly | `192.168.86.38`| ✅ Aligned | Cooldown: 30 minutes. |
| **Pool Pump** | Shelly | `192.168.86.198`| ✅ Mapped | Shelly 1 Mini G3. |
| **Garage (Left)**| Shelly | `192.168.86.33`| ✅ Mapped | Shelly relay control. |
| **Garage (Mid)** | Shelly | `192.168.86.24`| ✅ Mapped | Shelly relay control. |
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
| `.105` | Workstation | 1 | MacBook Pro (Current) |

## 📊 Data Collection Summary

- **House Temperature Delta:** Difference between hottest and coldest room.
- **House Average Temp:** Whole-house thermal average.
- **AdGuard Metrics:** DNS query and block rates flowing to VictoriaMetrics.
- **DNS Performance:** Quad9 (17ms), Cloudflare (20ms).
- **TTL Optimization:** Global minimum TTL set to 3600.

## 🛡️ Safety & Reliability

- **Emergency Safety:** `safety_smoke_co_emergency`. HVAC shutdown + Full lights on fire/CO.
- **DNS Watchdog:** `infrastructure_adguard_watchdog`. Auto-restarts AdGuard.
- **Laundry Monitor:** Robust state-based template (survives HA restarts).
- **House Occupancy:** Combined binary sensor for all 14+ occupancy sources.
