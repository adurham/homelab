# Sony Bravia Android TV Optimizations

**Date:** March 1, 2026
**Target Device:** Sony Bravia TV (`192.168.86.195`)

This document outlines the performance, memory, and telemetry optimizations applied via ADB to the Sony Bravia Android TV to improve speed, free up RAM, and reduce background network usage. It also serves as the master record for all TV picture, audio, soundbar, and console settings.

---

## Part 1: Android OS System & Hardware Tweaks (via ADB)

The following commands were applied to limit background memory usage, stop unnecessary Wi-Fi polling, and force hardware-accelerated UI rendering.

```bash
# Disable background Wi-Fi scanning (saves CPU/Network)
adb shell settings put global wifi_scan_always_enabled 0

# Limit maximum cached background processes to 4 (frees up RAM for active apps)
adb shell settings put global activity_manager_constants max_cached_processes=4

# Disable OS-level telemetry/APK uploading
adb shell settings put global upload_apk_enable 0

# Force GPU (OpenGL) rendering for 2D UI elements (improves menu fluidity)
adb shell setprop persist.sys.hwui.renderer opengl
```
*(Note: `send_action_app_error` was also disabled, but Android resets this secure flag on reboot, which is normal behavior).*

### Disabled Bloatware & Services
To free up over 500MB of RAM and prevent unnecessary CPU WakeLocks, 32 non-essential packages were disabled.

**Command Used:**
`adb shell pm disable-user --user 0 <package_name>`

#### 🛑 Telemetry & Logging
*   `com.sonyericsson.idd.agent`
*   `com.sony.dtv.crashlogcollector`
*   `com.sony.dtv.sonybugreportsys`
*   `com.google.android.feedback`
*   `com.sony.dtv.sonyloglevelsetting`

#### 🛑 Heavy Google Services & UI
*   `com.google.android.katniss` (Google Assistant / Voice Search - Freed ~370MB RAM)
*   `com.google.android.youtube.tv` (Stock YouTube app - Freed ~163MB RAM)
*   `com.google.android.youtube.tvunplugged` (YouTube TV)
*   `com.android.printspooler` (Android printing service)

#### 🛑 Sony B2B / Pro Mode Services
*   `com.sony.dtv.browser.webappplatform` (Crashing loop fix - March 2026)
*   `com.sony.dtv.b2b.noderuntime`, `com.sony.dtv.b2b.noderuntime.core`, `com.sony.dtv.b2b.noderuntime.system`, `com.sony.dtv.b2b.deviceadminsettings`, `com.sony.dtv.b2b.adminpassword`, `com.sony.dtv.b2b.settingproxy`, `com.sony.dtv.b2b.noderuntimeextension.bpk`, `com.sony.dtv.b2b.vendorprotocol`, `com.sony.dtv.b2b.ipcontrolsettings`, `com.sony.dtv.b2b.noderuntimeextension.node_18_12_1`

#### 🛑 Retail Demo & Sponsor Apps
*   `com.discovery.discoveryplus.mobile` (Discovery+)
*   `com.sonypicturescore` (Bravia Core / Sony Pictures)
*   `com.sony.dtv.smarthelp` (Interactive Help/Tutorials)
*   `com.sony.dtv.demosystemsupport` (Retail demo mode)

#### Notable Exceptions / Kept Packages
*   **AirPlay (`com.sony.dtv.airplayapp`):** Suspended via `pm suspend`. This prevents the Sony watchdog from force-restarting it like a standard `disable` command does. (March 2026)
*   **Netflix Partner Service (`com.netflix.partner.ncm`):** Left enabled. Disabling this breaks DRM (Widevine L1) and hardware acceleration for Netflix.
*   **Streaming Apps:** Amazon Prime Video, Pluto TV, Disney+, Hulu, Peacock, Apple TV, and Spotify were left fully active. (Note: Amazon and Pluto were re-enabled March 2026).

---

## Part 2: TV Picture Calibration (Reference Standards)

### Global Picture Settings (SDR / Standard Content)
*   **Eco Dashboard:** Light Sensor / Ambient Optimization **OFF**, Auto Power Saving **OFF** (Crucial for consistent brightness).
*   **Picture Mode:** Professional (Custom on older models).
*   **Contrast:** 90
*   **Gamma:** 0 (or -2 for pitch-black rooms).
*   **Black Level:** 50
*   **Color Temperature:** Expert 1 (Warm/Industry Standard D65).
*   **Live Color:** Off (For accuracy) or Low (For visual pop).
*   **Sharpness:** 50 (Neutral - 0 adds blur).
*   **Reality Creation:** Off (Unless watching 720p/1080i, then set to Manual 20).
*   **Motionflow:** Off (Or Custom with Smoothness 1 for stutter reduction).
*   **CineMotion:** High.

### HDR Settings
*   **Brightness:** Max
*   **HDR Tone Mapping:** Gradation Preferred.

---

## Part 3: Audio & Sony HT-A5000 Soundbar Settings

### TV Audio Output Settings
*   **Speakers:** Audio System
*   **Audio System Prioritization:** On
*   **A/V Sync:** Auto
*   **eARC Mode:** Auto
*   **Digital Audio Out:** Auto 1 (Passes raw, uncompressed surround data).
*   **Pass Through Mode:** Auto
*   **Acoustic Center Sync:** On (Only if S-Center cable is connected to TV, otherwise Off).
*   **Advanced Auto Volume:** Off (Let the soundbar handle this).
*   **Dolby Dynamic Range:** Standard (Uncompressed cinema experience).
*   **DTS Dynamic Range:** Off
*   **AC-4 Dialog Level:** +2 to +4 (Boosts dialogue in newer broadcast codecs).

### Soundbar HDMI & Wireless Settings
*   **Control for HDMI (CEC):** On
*   **eARC:** On
*   **Standby Through:** Auto
*   **HDMI Signal Format:** Enhanced format (4K120, 8K)
*   **TV Audio Input Mode:** Auto
*   **Wireless RF Channel:** On (Auto-switches to avoid Wi-Fi interference).
*   **Wireless Playback Quality:** Sound Quality (Use "Connection" only if rears/sub are stuttering).

### Soundbar Audio Processing & Manual Levels
*   **360 Spatial Sound Mapping:** ON (Creates the Atmos bubble using rears/up-firing speakers).
*   **DSEE Extreme:** ON (Upscales compressed audio).
*   **Audio DRC (Dynamic Range Control):** OFF (CRITICAL: Preserves the impact of loud effects and quiet whispers).
*   **Advanced Auto Volume:** ON (Evens out volume jumps between apps/videos).

**Manual Speaker Calibration (Customized for asymmetric room with left-side cat tower & rear speakers):**
*Must disable 360 Spatial Sound Mapping to enter values, then re-enable and run Sound Field Optimization.*
*   **Distances:** Front 12ft, Subwoofer 4.75ft, Ceiling 5.5ft, Rear L 6ft, Rear R 7.25ft, Sidewall L 5.25ft, Sidewall R 6.5ft.
*   **Levels:**
    *   Front: 0.0 dB
    *   Height: +4.0 dB (Boosts overhead Atmos effects)
    *   Subwoofer: +2.5 dB
    *   Beam Tweeter Left: 0.0 dB (Left at baseline due to rear speaker compensation)
    *   Beam Tweeter Right: 0.0 dB
    *   Rear Left: 0.0 dB (Quieter because it is physically closer)
    *   Rear Right: +1.5 dB to +2.0 dB (Boosted to pull the center soundstage back to the middle)

---

## Part 4: PlayStation 5 (Game Mode) Setup

### Hardware & Port Configuration (Hue Sync Box 8K Setup)
Because you are using the **Hue Sync Box 8K**, which supports HDMI 2.1 (120Hz/VRR), the wiring order is critical to prevent handshake failures with the soundbar:
1.  **PS5** -> **Hue Sync Box 8K** (Use Port 2 or 4).
2.  **Hue Sync Box 8K** -> **TV** (HDMI 4 - Set to *Enhanced format (VRR)*).
3.  **Sony HT-A5000** -> **TV** (HDMI 3 eARC port).
*(Note: Do not plug the Sync Box into the Soundbar's HDMI IN port, as the Soundbar's passthrough often drops the VRR handshake from the Sync Box).*

### TV Game Mode Settings
*   **Picture Mode:** Game (Auto-switches via ALLM).
*   **HDR Tone Mapping (TV):** Gradation Preferred (Allows PS5 to handle Auto Tone Mapping).
*   **Motionflow / A/V Sync:** OFF (Guarantees lowest input lag).
*   **Color Temperature:** Expert 1.
*   **Live Color:** Off (for accuracy) or Low (for vibrant pop in stylized games).

### PS5 Console Settings
*   **Resolution:** Auto
*   **VRR:** Automatic (Eliminates screen tearing).
*   **120Hz Output:** Automatic
*   **ALLM:** Automatic
*   **HDR:** On When Supported
*   **Adjust HDR:** First two screens set until the symbol barely vanishes; third screen set all the way down (to perfect black).
*   **Audio Output Device:** AV Amplifier (Because of the physical rear speakers).
*   **Number of Channels:** 7.1
*   **Audio Format (Priority):** Dolby Atmos (Translates Tempest 3D Audio into Atmos for the HT-A5000).
    *   *Note: If you experience audio delay in competitive shooters, switch this to Linear PCM.*
*   **4K Video Transfer Rate:** If you experience screen flickering due to the Hue Sync Box, change this from "Automatic" to **-1** or **-2**.

---

## Part 5: Known Hardware Quirks & SoC Troubleshooting

### The MediaTek "High Load" Reporting Quirk (SoC: Pentonic 1000)
On most Sony Bravia TVs (including XR80), `adb shell uptime` or `top` will report a sustained load average between **15.0 and 30.0**, even when the system is idle.
*   **Cause:** This is a reporting artifact of the MediaTek kernel. Display and GPU drivers (`mtk_disp_mgr`, `DispLink`) keep kernel threads in **Uninterruptible Sleep (D-state)** while waiting for hardware events.
*   **Diagnosis:** If the load is high but **CPU usage is <5%**, the system is healthy. If CPU usage is high, a background process (usually `webappplatform`) is runaway.

### The "26-Hour Standby" Watchdog Bug
A known firmware flaw in the MediaTek Pentonic 1000 SoC causes the system to hang or enter a reboot loop approximately 6 minutes after entering standby if the uptime exceeds 26 hours.
*   **Mitigation:** The debloat list in Part 1 (specifically disabling `com.google.android.katniss` and `com.sony.dtv.browser.webappplatform`) reduces the memory pressure that often triggers this watchdog event.
*   **Fix:** Ensure firmware is `112.631.085.1` (Feb 2025) or higher.

### Driver Deadlocks (Wi-Fi & Power Management)
There is a documented race condition between the `mt792x` Wi-Fi driver and the kernel Power Management (`ps_work`) threads.
*   **Symptoms:** Complete system freeze followed by a forced reboot.
*   **Trigger:** Usually occurs when the TV is attempting to sleep/wake while background network activity is high.
*   **Future Stability Fix (If Crashes Persist):**
    If reboots continue, run the following to disable **Remote Start (Wake on Wi-Fi)**. This will eliminate the driver deadlock but will break "Turn ON" for Google Home/Home Assistant (CEC via PS5/Soundbar will still work).
    ```bash
    # Disable Remote Start / Wake on Wi-Fi
    adb shell settings put global remote_control_pkg_name ""
    adb shell settings put global remote_start_status 0
    ```
