# IPAM — IP and VMID allocation

Single source of truth for IP allocations and Proxmox VMIDs. Keep this in
sync when adding/removing/moving CTs or VMs.

## Networks

| Network         | CIDR              | Bridge  | Purpose                                    |
| :-------------- | :---------------- | :------ | :----------------------------------------- |
| LAN             | `192.168.86.0/24` | `vmbr0` | Home LAN — DHCP from the Nest router       |
| Private (VXLAN) | `172.16.0.0/24`   | `private` | SDN private subnet for service traffic   |
| BWT Lab (VXLAN) | `10.99.0.0/24`    | `bwt`     | Isolated subnet for Tanium bandwidth-throttle repro (NEC 00271560 et al) |
| PVE Sync (VLAN 20) | `172.20.0.0/24` | `vmbr0.20` | Isolated L2 segment for corosync + ZFS replication, physically confined to switch ports 3/4/5 — see below |

### LAN static-IP allocations (outside the Nest router's DHCP pool)

Google Nest/Wifi's default DHCP pool is **192.168.86.20-250** (confirmed
via vendor docs + a live nmap sweep 2026-09-10 finding active DHCP
leases scattered up to .235, consistent with that default never having
been customized). That leaves **.2-.19** and **.251-.254** safe for
static allocations. No local API/CLI exists to change or query this
scope directly (Nest's local HTTP API needs cloud/app auth; there's no
SSH/SNMP access) — the Google Home app is the only way to verify/change
the actual pool boundary if it's ever suspected to have changed.

Current static allocations in the safe-outside-DHCP range:

| IP | Host | Notes |
| :--- | :--- | :--- |
| `192.168.86.1` | Nest router | gateway |
| `192.168.86.2` | Home Assistant (HAOS) | hosts AdGuard Home add-on for DoT upstream + iOS push |
| `192.168.86.11` | `pve01` | |
| `192.168.86.12` | `pve02` | |
| `192.168.86.13` | `pve03` | |
| `192.168.86.16` | `tailscale-gw` | eth0/vmbr0 -- was DHCP until 2026-09-10 (see Service CTs table below for why) |
| `192.168.86.85` | `frigate-01` | eth0/vmbr0 -- was DHCP until 2026-09-18 (lease drifted to .45 after a cluster-wide reboot, breaking every hardcoded consumer of this IP; same failure class as tailscale-gw above). NOTE: this address is INSIDE the Nest router's DHCP pool (.20-.250), unlike the other static entries here -- accepted precedent already exists (lb-01 at .86, immediately adjacent) but if .85 ever gets DHCP-assigned to another device first, this will conflict. Consider migrating to a reservation or an out-of-pool IP if that ever happens. |

`.14`/`.15` also showed as live in the same nmap sweep — identity not
confirmed, left alone. `.17`-`.19` still free if another static
allocation is needed.

## Physical switch chain (LAN, non-Proxmox)

Physical topology upstream of pve01/02/03 and the exo cluster Mac Studios:

```
AT&T BGW (IP Passthrough)
  -> Google Nest Wifi Pro (main unit, living room)
       -> TP-Link TL-SG105E (5-port managed, .15) — first hop off the Nest
            -> 8-port basement "trunk" switch (unmanaged) — branch hub
                 -> 5-port under-work-desk switch (unmanaged) — DIRECT cable
                    from the trunk; no pod in the path (since 2026-09-30)
                      -> NETGEAR GS108Ev4 (lab switch, .51) -> PVE
                         nodes + Mac Studios + Nest Wifi Pro basement pod
                         (.40) as a LEAF (user, 2026-09-30: "off the homelab
                         switch"; port not verified) — nothing on the pod's
                         LAN port, no structural traffic through it
                 -> game-room switch (unmanaged) — pod there was reset
                    2026-09-25; a second Nest pod answers at .39 (uptime 3.7 d
                    on 2026-09-30). That it IS the game-room pod, and how it
                    is cabled, are NOT verified (rule: leaf only, nothing in
                    its LAN port)
```

(Re-cabled 2026-09-30 14:50-14:56 CDT per the user: pod removed from the path
— direct trunk -> under-desk cable, pod re-attached as a leaf. This replaces
the 2026-09-25 diagram in which the basement pod sat INLINE between the trunk
and the under-desk switch (the SPOF in the incident below). Chain + ordering
per user description; port-level interconnects below the trunk are not
individually verified.)

### INCIDENT 2026-09-25 evening: basement pod inline = whole-homelab SPOF (CONFIRMED)

User had been trying to force the basement pod onto wired backhaul, couldn't,
and removed it from the mesh via the Google Home app (not a power-cycle).
Within minutes, pve01/02/03, both Mac Studios, and (transiently) the SG105E/
HA/frigate/lb-01 all went unreachable — a live re-run of the same
"unexplained blackout" fingerprint logged twice earlier that day, but this
time root-caused in real time by a Hermes session.

**Confirmed root cause:** the pod, being wired INLINE between the basement
trunk switch and the under-desk switch (see corrected diagram above) rather
than as a leaf, stopped bridging its WAN<->LAN ports entirely once pulled
from the mesh — a known Nest pod failure mode when de-meshed via software
instead of power-cycled. That silently cut the ONLY path to the under-desk
switch, the Netgear homelab switch, all 3 PVE nodes, and both Mac Studios,
while leaving WiFi clients, the Nest's own WAN, and anything not behind the
pod (HA, frigate, lb-01, tailscale-gw, SG105E) only transiently affected by
initial mesh-reconfig churn (self-recovered within ~10 min).

**Proof it was a pure path cut, not a power/host event (verified via SSH the
moment the path came back):** all three PVE nodes' `uptime` traced back to
the EARLIER same-day 14:53 boot (the previously-logged 14:48-14:53 crash
event) — none of them rebooted during this incident. `pvecm status` showed
`Quorate: Yes, Nodes: 3` throughout on recheck, and no new NIC link-down
events appeared in any node's dmesg. This makes sense structurally: corosync
traffic between the 3 PVE nodes flows through the Netgear switch, which sits
entirely DOWNSTREAM of the dead pod alongside the nodes themselves, so
inter-node cluster traffic never had to cross the broken link at all — only
reachability FROM outside the pod (this laptop, upstream generally) was cut.

**Fix applied (temporary):** user re-added the pod to the mesh (~19:34-19:41
CDT); forwarding resumed and the whole path stabilized by ~19:45, confirmed
clean for 6+ continuous minutes plus live SSH/pvecm checks after.

**Root-cause fix — APPLIED 2026-09-30 ~14:50-14:56 CDT** (user re-cabled;
verification in the 2026-09-29/30 storm entry below): a direct cable now runs
from the basement trunk switch to the under-desk switch, bypassing the pod
entirely, so the PVE cluster + both Mac Studios are no longer structurally
dependent on any Nest pod's mesh membership/backhaul state. This also resolves the original "can't force wired backhaul"
complaint for free — once the pod carries no structural traffic, there's
nothing that needs forcing; it can stay on wireless backhaul (or unplugged)
as pure WiFi coverage with zero blast radius if it acts up again. Given this
network has already burned through 2 confirmed-degraded pod units (fact
1650/1649) that showed exactly this kind of "won't behave" symptom before
failing outright, treat this pod's original wired-backhaul refusal as a
possible early warning sign worth revisiting, not just user error.

**Post-incident verification (~20:00-20:05, same evening):** user confirmed
via the Google Home app's Device settings screen that the basement pod
(LAN IP **192.168.86.40**, model G6ZUC) now shows **Connection type: Wired**
— the re-add did restore wired backhaul, not just mesh membership. Cross-
checked locally: `.40` pings tight (avg 9ms, stddev 4ms — matches the
documented wired-pod ping-jitter signature) and returns a plain HTTP 404
rather than a refused connection (unlike real pod hardware, which refuses
every port — worth noting as a device-type distinction if `.40` gets probed
again later). Main/living-room unit confirmed LAN IP 192.168.86.1, WAN IP
108.88.208.88, model G6ZUC also. The two net_a1_6e76/net_a1_c76a mDNS names
at .218/.220 seen earlier in this incident are NOT the basement pod (that
guess was wrong) — likely the game-room pod (reported unplugged/reset
earlier the same day) in some transient state, or stale entries; not
resolved on a later targeted re-check, not chased further since they're
outside what was actually being verified.

**Loop-prevention state across the chain (2026-09-25):**

| Switch | Type | Loop prevention |
| :--- | :--- | :--- |
| NETGEAR GS108Ev4 (.51) | managed | **OFF** (user, 2026-09-25) — its LED "both LEDs blink at constant speed" report had been seen; disabling caused no storm (verified host-side) |
| TP-Link TL-SG105E (.15) | managed | ON — and demonstrably NOT blocking: backbone ports 1/5 forwarding ~2.8k pkt/s each (measured 2026-09-25). No action needed. |
| Basement trunk (8-port) | unmanaged | DIP OFF (user) |
| Game-room / under-work-desk | unmanaged | physical DIPs, if present — per-switch basic detection only; leave as-is. These toggles are NOT a fix for anything; they only decide whether that switch auto-blocks a port when it detects a loop. |

Managed switches keep their loop prevention under DIAGNOSTICS → LOOP
PREVENTION; the TL-SG105E exposes `lpEn` on `/LoopPreventionRpm.htm`.

**Storm re-check + two real LAN blackouts (2026-09-25 ~15:00, re-verified on
user challenge).** No storm in any measured window: multi-vantage byte/packet
rates at every layer normal, zero CRC/error counters, no duplicate-source
traffic. The `SUSPECT-STORM` lines in the studios' `/tmp/netwatch24.log`
(13:42 and ~15:00) coincide with the port-mapping bulk transfers run by the
earlier session — the 15:00 one is byte-verified (pve02 `tap200i0`/VM200 rx
peak 14.42 MB/s = the 400 MB download) — and the watcher's ~1,000 pkt/s
threshold is far too low: **treat any future `SUSPECT-STORM` line as needing
a byte-rate check before it is called a storm.**

Separately, TWO real transient segment blackouts were found that had not
been recorded: **12:28:29–12:28:58** (all three pve NIC links dropped
simultaneously ~30 s; corosync lost quorum, recovered) and
**~14:48:59–14:53** (gateway unreachable from MacBook + studios; at ~14:50
all three pve nodes hard-reset uncleanly — `last` shows "crash", fsck ran at
boot — back up 14:54–14:56). House power stayed up through the window (HA
whole-home power sensors kept reporting). A storm floods; these were
blackouts (loss + LOW counters). Cause NOT yet identified. Watch items: this
is the same simultaneous-3-node reboot class as 2026-09-20 (power-event
precedent); pve03's boot HDD (ata1) threw SATA link resets again at 15:06;
Netgear port 5 (documented = pve01) reads `100M full` while pve01's own NIC
reports 1000 Mb/s — verify mapping/renegotiation. Loss-triggered watchers
armed on both studios (`/tmp/netwatch_power.log`).

### INCIDENT 2026-09-29/30: overnight LAN storm -> Healthchecks DOWN; pod removed from the path

**Symptom.** Healthchecks.io `homelab-grafana-watchdog` went DOWN 00:43:05 CDT
and back UP 00:48:00 (email: "downtime 4 minutes, 55 seconds"). Grafana
(graf-01, CT107 on pve01) never stopped — rules evaluated every minute all
night. Its dead-man's-switch pings to hc-ping.com failed at ~00:38:25 and
~00:43 with `TLS handshake timeout` (other windows: DNS timeouts to
172.16.0.10): off-segment TCP was failing, the lab's own services were not.
The later resets that day (pve02 02:34; all three nodes 13:01 = INCIDENT
CLASS B) post-date the alert and are NOT its cause.

**The night (CDT).** Onset 2026-09-29 20:29:17 after a clean 7.5 h (first
gateway=DOWN in both studios' `labwatch.log`). labwatch state transitions per
hour (macstudio-m4-1): 20h 21, 21h 18, 22h 95, 23h 161; 09-30 00h 215, 01h 153,
02h 99, 03h 50, 04h 86, 05-08h 25/24/59/41, 09-11h 8/2/12, 12h 19 (last flap
12:14:35), then quiet 12:14-14:50 bar the 13:01 reset. Both studios' `netwatch`
logged 100% loss to the gateway with `link=active` — the PHY never dropped, no
NIC link-down on any node. Kernel `vmbr0: received packet on nic0 with own
address as source address` (L2 loop/echo fingerprint), per Loki over 09-29
evening + 09-30: ~2.4k / 2.7k / 2.4k on pve01/02/03 (0-4 on the quiet days 09-26..28; 5-29 on the
09-25 blackout day). Corosync KNET flapping, tailscale-gw relay churn and outbound failures
on lb-01 / hermes-gw-01 / vm-01 in the same windows.

**Who flapped, who didn't.**
- Clean: AT&T BGW320 (uptime counter: no reboot since 09-25; WAN 0 errors, GPON
  O5), Nest main (no reboot since 09-28), every node NIC, graf-01 itself.
- Flapped in lockstep on DIFFERENT paths: the wired lab corner (studios ->
  gateway loss, SG105E .15, KNET); Home Assistant (.2, wired on the trunk,
  upstream of the pod zone — Emporia cloud poll 59 unavailable windows overnight
  vs 1-5 on quiet nights); WiFi-only clients (Sony TV 100 unavailable windows
  18:00-06:00 vs 0/1/4 on clean nights; Shelly/EcoNet/heat-pump entities).
- Reading: a disturbance on the flat LAN that reached at least the trunk/SG105E
  layer AND the WiFi side while sparing the BGW/WAN => Nest main + the L2 fabric
  under it, not the ISP. A single failing port cannot explain flapping on paths
  that share none. TRIGGER NOT IDENTIFIED (nothing logged at 20:29; the GS108's
  own counters/uptime are not readable remotely without the 1Password login).

**Change (user, 2026-09-30 14:50-14:56 CDT; the watchers show the gateway /
SG105E / pod blip while cables moved, settled 14:55:56).** Basement pod taken
out of the path (direct trunk -> under-desk cable; pod now a leaf off the lab
switch, nothing on its LAN port). It rebooted at ~14:54:30 (status-API uptime) and answered pings again at 14:55:38 (labwatch).
Effect: the lab corner no longer depends on any pod's mesh/backhaul state
(closes the 2026-09-25 SPOF) and the inline-bridge loop surface is gone.

**Verification 14:56 -> 17:17 CDT (2h21m), all read live:**
- dup-source-MAC kernel lines: 0 on all three nodes since 14:56, by the nodes'
  journals AND by Loki (independent of them; journal ingest confirmed flowing
  the whole window; Loki checked through 17:35). Last events before the change,
  per Loki: pve02 ~08:55, pve01 ~11:07, pve03 ~12:10. Caveat: pve02/pve03
  journals are Storage=volatile and were wiped by the 13:01 reset, so only Loki
  (and pve01's persistent journal) can see earlier. Corosync KNET events: 0.
  Quorate 3/3.
- Active echo test (10 broadcasts out per node; inbound frames carrying the
  node's OWN source MAC): 0 returned on pve01/02/03.
- Natural canary: an ecobee thermostat (192.168.86.22, MAC 44:61:32:df:66:47)
  ARP-sweeps the whole /24 at 60-100 frames/s (seen in every capture today; a reported
  ecobee quirk; 84-95% of all broadcast frames; ~6 KB/s, trivial bandwidth). In a loop every such frame
  arrives 2+ times: 0 of 2,745 broadcast/multicast frames in 26 s on pve01 had
  an identical twin within 30 ms.
- labwatch (both studios): 0 state transitions since 14:55:56; netwatch: 0 loss
  lines. Loss from pve01: 0% to gateway .1 (0.5-0.8 ms), SG105E .15 (2.2),
  basement pod .40 (0.42 — wired-fast; the WiFi-only ecobee averages 16 ms),
  HA .2 (0.39), GS108 .51 (1.9), studios .47/.48 (0.36).
- HA, 166 WiFi/cloud-side entities: 1 transition to unavailable since 14:56 (a
  Shelly temperature sensor) vs 55 flap-minutes in last night's worst hour.
- Fleet: all CTs running, tms-01 up (:22/:5433); the only down scrape targets
  are the two un-launched exo nodes (expected). The 21 stopped VMs on pve01
  (usda-*, win-*, templates) are onboot=0 by design.

**NOT proven.** The same watchers had a 2.5 h quiet spell (12:14-14:50) before
the change and the dup-frame counter had already stopped by ~12:10, so a clean
afternoon is not evidence by itself; storms ran ~20:30-05:00 (plus a light
11-12h tail). The test is a storm-prone window. Pass = dup-source-MAC lines ~0
per node and labwatch <~5 transitions/hour through 20:30 -> 06:00; fail = the
signature returns, which exonerates the pod and leaves Nest-main bridging and
the SG105E/trunk. Open, no programmatic readout: both pods' `/api/v1/status`
read lan0Link/ethernetLink = false despite wired-fast RTT, so the Google Home
app's Connection type is the only authority on wired-vs-wireless backhaul. GS108
loop prevention is still OFF (table above); second pod .39 placement unverified.

### INCIDENT CLASS B: recurring simultaneous 3-node hard resets (2026-09-28 analysis)

Separate from the pod/SPOF outages above. Five events, all three pve nodes
dead within seconds of each other, unclean (no shutdown sequence, no panic
in pstore, no HA watchdog/fence log line), while house power stayed up on
every circuit:

| Boot time (UTC) | Notes |
| :--- | :--- |
| 2026-09-16 21:03 | journal stops mid-traffic, 68s gap before boot |
| 2026-09-18 17:36 | pve02/03 journals already vacant (rotation) |
| 2026-09-20 20:57 | 20+ min of silence before the boot on pve02/03 |
| 2026-09-22 00:12 | stagger 00:10:38 / 00:11:08 / 00:11:13 |
| 2026-09-25 19:53 | stagger 19:48:16 / 19:50:22 / 19:50:29 |
| 2026-09-30 02:34 | SINGLE-node (pve02 only) — see separate note below |
| 2026-09-30 13:01 | stagger 13:01:21 / :26 / :26 (CDT; boots 18:01:21Z/:26Z) — FIRST EVENT CAPTURED LIVE by all three witnesses |

**EVENT 2026-09-30 13:01 CDT (18:01Z) — captured live by the instrumentation.**
All three nodes' journals stop mid-flight between 13:00:27 (last line) and
13:01:21 (pve01 kernel first line); `last -x` = "crash" on all three; pve01
journald logged `File .../system.journal corrupted or uncleanly shut down,
renaming and replacing` at boot. No pstore entries on any node. No
HA/fence/watchdog log line before death (same signature as prior events).

Witness evidence (all three /root/lab_witness.log + both Studios'
/tmp/labwatch.log) shows the discriminating pattern for this occurrence:

- At 13:00:43 pve03's own last heartbeat: `nic0=up quorate=Yes`. At 13:01:00
  (first sample after) BOTH Studios' labwatch logged `netgear-gs108=DOWN`
  (tplink + nest-pod + gateway stayed UP) while pve01/02/03 were already
  DOWN — i.e. ALL THREE nodes + the Netgear GS108 went dark together, while
  the upstream TP-Link SG105E, Nest pod, gateway and both Studios rode it out.
- netwatch_persistent on both studios shows ZERO loss/latency anomaly in the
  ~3 minutes before 13:01 (last pre-event sample 12:59-13:00: `LOSS=0%`), so
  this was a hard cut, not a degrading link.
- Recovery stagger: pve01 up first (13:01:33), then sg105e/netgear (13:01:35-48),
  then pve03 (13:01:54) and pve02 (13:01:57); labwatch returns all-UP 13:01:25→13:02:07.
- House power: whole-house CT `sensor.edgewater_road_power_minute_average`
  stayed 2880-3766 W straight through 17:50-18:10Z (no dip <100 W). (Same
  caveat as before: a 1-min average cannot see a sub-second sag.)
- SMART: pve02 unsafe-shutdowns 119→120 and pve03 unchanged at 157 across
  this event (pve03 counter is stale/inconsistent — it did not increment even
  though the node hard-reset; treat per-event deltas as unreliable on pve03).
  All three nodes are still running their pre-event kernels/uptimes reset at
  13:01; no fsck errors surfaced at boot (`fsck` slice exists on all three).
- Blast radius that rode it out: all LXCs and VMs came back (both Studios
  never rebooted; HA host uptime unbroken; the Netgear switch answered :80
  immediately after; CT uptimes all 18:02-18:04Z = restarted with their nodes).

**This occurrence is the strongest discriminator yet, and it points AWAY from
the pure "three independent PSUs" framing:** pve03's witness heartbeat was
`quorate=Yes, nic0=up` at 13:00:43 and dead by ~13:01:00, and the Netgear
GS108's mgmt plane vanished in the SAME instant as the nodes (both studios
saw it), while the SG105E (upstream of the GS108) stayed up. That is
consistent with a power/feed event on the shared branch feeding the
Netgear+PVE corner (mechanism (a)), NOT with an HA self-fence (mechanism (b))
— a fence would not take the separate Netgear switch's own mgmt IP down, and
would leave the fence log line + softdog reason; neither exists. Next
occurrence: physically inspect the strip/branch feeding that corner, and
check whether the GS108's own uptime counter reset (its web UI at
192.168.86.51 now answers; a single read-only visit is allowed, do NOT loop
logins).

**EVENT 2026-10-01 13:23:57 CDT (18:23Z) — SECOND event captured live; first with a full node-side reconstruction.**

This is now the strongest evidence set in the series, and it refines the
mechanism to a SHORT DEEP POWER SAG on the lab corner. Captured entirely from
node-side instrumentation (the 1s TCP witnesses) + Loki + VictoriaMetrics:

- **Death order (per the survivors):** pve03's witness logged `pve01=down`
  at 13:24:00, `pve02=down` at 13:24:01 — BOTH dead within ~1-2s of each
  other. pve01's own last witness line was 13:23:41 and its journal ends
  mid-connection-traffic (sshd churn) at 13:23:41 with NO shutdown sequence,
  no kernel message, no panic. pve02's last Loki line: 13:23:56.207. Both
  died `crash` (wtmp), no pstore.
- **pve03 SURVIVED but its NIC carrier dropped for exactly 19s:**
  `e1000e nic0: NIC Link is Down` at 13:23:58 → `Link is Up 1000 Mbps Full
  Duplex` at 13:24:17. It stayed quorate, served through, and its HA lock
  blipped only briefly (watchdog closed 13:24:05, `watchdog active` again
  13:24:40 — no fire, margin never exhausted).
- **Power-return math from boot timers:** pve01 `Startup finished in 17.6s
  (firmware) + 9.792s (loader) + ...`, boot_time 13:24:27 ⇒ power-on ≈
  13:23:59.5; pve02 firmware 18.331s + loader 15.315s, boot_time 13:24:32
  ⇒ power-on ≈ 13:23:58.6. So the interruption was only ~2-13 seconds —
  a SAG, not an outage: power was back before the nodes' ATX supplies
  fully drained, and pve03's rail never dropped below its PS-ON threshold.
- **Blast radius, corrected reading (2026-10-01 20:40):** pve03's link partner
  port went down for the full 19s (its PHY logged carrier loss 13:23:58 →
  link back 13:24:17; the GS108 answered again 1s AFTER link return). The
  upstream SG105E's mgmt plane stayed unreachable ~15s LONGER than the
  survivor's own link recovery (down 13:24:03, up 13:24:32) — independent
  evidence the disturbance reached above the corner. CAVEAT: the netgear and
  router probe "down" windows (13:24:02→:18, 13:24:04→:19) overlap pve03's
  OWN link outage, so they are NOT independent evidence those devices
  rebooted this time — do not cite them as such. Everything recovered; none
  of the CTs/guests were corrupted.
- **House power CT:** 18:24 sample 3164 W (no dip; adjacent minutes
  2832-2905 W) — consistent with past events (1-min average cannot see a
  sub-second sag).
- **All other lab hosts** (the whole CT fleet on all three nodes) died and
  rebooted with their nodes at 18:24:27-32Z — 23 instances' boot_time
  reset in VictoriaMetrics at that second.
- **FREQUENCY IS INCREASING:** this is the 3rd occurrence in 35 hours
  (Sep30 02:34 pve02-solo, Sep30 13:01 all-three, Sep30 21:05 pve02-solo,
  Oct1 13:24 pve01+pve02), vs one every ~2-4 days before. pve02 died in
  ALL FOUR; it is the canary (lowest ride-through on the strip).

**Mechanism conclusion:** the pattern is a short (seconds-long) deep voltage
sag on the branch feeding the lab corner, with per-PSU ride-through
differences deciding who survives. What kills the alternatives: a clean
series break would take everything to power-on instantaneously with zero
recovery stagger AND no survivor; HA self-fence is excluded by timing (deaths
<25s after a healthy quorum heartbeat vs the 60s softdog margin, no fence
lines); and the load-bearing discriminator vs a NETWORK fault is physical —
two hosts hard-died instantly with zero pre-death signature AND the surviving
third host's NIC carrier dropped in the same second. No network fault
hard-kills a host, and none resets a live host's PHY carrier. Consult
(glm-5.3, 2026-10-01) independently read the same evidence and endorsed:
"strip-level power interruption; switch died and rebooted; pve01/pve02 died;
pve03's PSU rode through" and noted the stagger means a DECAYING/CHATTERING
voltage (arcing contact or thermal breaker near threshold), which matches the
increasing frequency and makes this a potential FIRE-RISK progression, not
just a reliability nuisance.

**Actions taken 2026-10-01:**
- `lab_witness.sh` v2 deployed to all three nodes (repo
  `scripts/network/lab_witness.sh`): added a `wan` probe (TCP 1.1.1.1:443)
  so the next event can separate house/WAN-side from lab-local, and the
  probe list now covers the corner switches + router.
- Incident record: this entry. Next-event protocol below.

**REFINEMENT (2026-10-01 evening, user input): the suspect is the OLD POWER
STRIP's contacts, not any grid/brownout condition.** The user confirmed the
strip is old. Key discriminator against a house-brownout reading: a real
brownout affects every circuit and would show in the Emporia data across the
house. It does not — Emporia shows the basement circuits calmly at 2-211W
during the events, whole-house never above ~20kW/30d peak, nothing anywhere
near overload, and the rest of the house rides every event cleanly. This is
NOT an overload or a house-wide sag.

What the data CANNOT see: the strip and its sockets/plugs are DOWNSTREAM of
every CT clamp. A failing contact (arcing, corrosion, spring gone weak) only
affects devices physically plugged into THAT strip, and draws no measurable
power — invisible to any CT. So "Emporia shows no problem" is fully
consistent with a strip-contact fault; it rules out overload/sag, not the
strip itself.

Also note the survivor nuance: pve03 shares the strip but survived with a 19s
PHY blip rather than dying. Two candidates: (a) per-device PSU hold-up
differences (same strip event, only the two most sensitive PSUs dropped), or
(b) pve02's own PSU/connector is degrading and its fault current is what
stresses the shared strip. pve02 died in ALL 4 recent events — canary or
instigator.

**The isolating experiment (free, no hardware):** move pve02 off the strip
onto a different circuit entirely, then wait.
- pve02 keeps dying alone -> its PSU/cord, replace that.
- the OTHER two start dying instead -> the strip (replace it).
- all quiet -> it was the strip contact, cured by moving.
An old strip with an escalating event frequency is a fire-risk item as well
as a reliability one: inspect for discoloration/warmth before trusting it.

**Next occurrence, first moves (updated):** read `/root/lab_witness.log`
on all three nodes for the drop ordering (node-side 1s witnesses are now the
primary instrument), then Loki for the final lines, then compute the
power-return time from `Startup finished` + boot_time. If a survivor shows a
NIC blip again, that's the sag signature. Physical: inspect the strip and
wall receptacle feeding the lab corner for discoloration/warmth (arcing =
fire risk), reseat all plugs, and consider a cheap UPS+NUT piped into
Loki/VM — it converts every invisible sag into a logged transfer event and
mitigates it simultaneously; with the current cadence a verdict lands within
days. Note the nodes share ONE strip (user, 2026-09-28) and pve02 is the
most sensitive point.

Evidence gathered 2026-09-28 (VictoriaMetrics `node_boot_time_seconds`
steps + Loki journals + HA per-circuit power):

- **Whole-house CT shows no outage** at any of the five instants
  (2-3 kW continuous, 1-min data) — but note a 1-min average cannot see a
  sub-second mains sag, which is exactly the class that resets desktop PSUs
  while smaller supplies ride through. So this is weak evidence, not proof.
- **Circuit-level sensors stay live** through the events (checked all 20
  power sensors; the only zeros are always-zero circuits like pool pump).
- **No UPS/NUT on any pve node** — nothing on these nodes can ride out even
  a brief interruption.
- **softdog is active with a 10s timeout** on all three, but softdog's
  timeout handler calls `emergency_restart()` which writes NO journal and
  NO pstore entry by design — so the absence of a logged reason is the
  EXPECTED signature of either a power event OR a softdog fire, and cannot
  distinguish them. `efi_pstore` IS registered on pve02/pve03.
- Simultaneity is the strongest signal: three independent hosts dying within
  ~10s of each other with no shared software path (no shared storage stall,
  no quorum loss, no lock-timeout) points at their common substrate — the
  physical feed.
- Not yet measured: the NETGEAR GS108Ev4's own uptime counter (would prove
  whether it rode the events out). The switch's dashboard exposes no uptime
  field via the CGI pages we can read; a scripted login burned the session
  slots on 2026-09-28, so this needs either a browser visit to the UI or a
  later attempt after slots expire. Do NOT retry logins in a loop — the
  switch wedges (see the lan-device-identification skill).
- **The three nodes share ONE power strip (user, 2026-09-28).** This is the
  first confirmed common physical substrate on the lab side, and it collapses
  the "three independent hosts" framing above: they are not independent at the
  feed. It is equally consistent with BOTH surviving hypotheses — a strip/branch
  fault kills all three at once (mechanism a), and HA self-fencing reboots all
  three at once after a shared connectivity loss (mechanism b). It does NOT by
  itself prove power. Note the strip holds only the three nodes, not the
  Netgear switch or the Mac Studios, so "did the switch ride it out?" remains a
  valid discriminator.
- **SMART power-loss counters are high on all three (read 2026-09-28):**
  `Unsafe Shutdowns` = 117 (pve01, 174 power cycles), 119 (pve02, 135),
  156 (pve03, 173). These are cumulative since the disks were installed and
  include every earlier crash, so they corroborate that abrupt power removal is
  this cluster's normal failure mode but do not date individual events.
  They are the one counter that survives the event on the powered-off node.
  The SMART textfile exporter (`roles/smartctl_exporter`, added 2026-09-16)
  exposes `smartctl_device_attribute`, but as of 2026-09-28 only the
  ata-*subset* attributes are exported — `unsafe_shutdowns` is not among them,
  so it is not yet trendable in VictoriaMetrics. Extending that exporter to
  include the nvme attributes is the cheap next step for dating each event.

**Timeline note (2026-09-28):** all five events are *reboots*, and three land
within seconds of a quarter-hour (Sep16 21:03, Sep18 17:36, Sep25 19:53 ≈
:53:5x; Sep22 00:12). pve01 additionally shows an in-place journald restart at
02:00:54 on 2026-09-28 with no boot, and pve02 at 22:53:03 the previous
evening — so something also restarts userspace/journald without a reboot.
Worth checking against cron/timer schedules on the branch before attributing
every event to hardware.

**Hardware note:** all three nodes are Dell OptiPlex desktops (pve01 7090,
pve02/pve03 5080). pve01 carries stale Dell `BsodForensicDump` EFI vars from
2025-04-18 (pre-dates this cluster's use) — not related to these events.

**Instrumentation armed 2026-09-28** so the next occurrence is captured
automatically:

- `/tmp/netwatch_persistent.log` on both Mac Studios — loss/counter-reset
  watcher (5s cadence, rotates at 5MB). Launcher `~/bin/start_netwatch.sh`;
  re-run after a reboot (launchd's GUI domain is not reachable over plain
  SSH on these Macs, so it is a nohup daemon, not a LaunchAgent).
- `/tmp/labwatch.log` on both Mac Studios — per-host reachability TRANSITION
  logger (TCP probes, correct for this LAN; see the ICMP note below).
  Logs a line only on a state change, so the next event yields precise
  per-host drop ordering: nodes-only vs switch+everything vs staggered.
- netconsole is NOT usable on these nodes: the only NIC is a bridge slave
  (`nic0` -> `vmbr0`) and netpoll refuses slave devices ("is a slave
  device, aborting"); naming the bridge picks a random veth port that
  netpoll also rejects. Confirmed and reverted 2026-09-28.

**LAN gotcha (verified 2026-09-28):** ICMP is filtered/deprioritized on this
LAN — the pve nodes, the TP-Link SG105E and even the gateway show 100% ping
loss from both a studio and hermes-gw-01 while their TCP ports are open
(pve01-03: icmp DOWN, tcp/8006 OPEN). Any future reachability watcher must
probe TCP, not ping; a ping-based version of labwatch produced a wall of
false DOWN lines before this was caught.

**Next occurrence, first moves:** read `/tmp/labwatch.log` on both studios
for the drop ordering, then `/tmp/netwatch_persistent.log` for packet-level
detail, then `last -x` + `journalctl -b -1` on each node, and grab the
Netgear's uptime from its UI by hand.

**THIRD occurrence, live during this same day's later session (~19:07-19:26+
CDT), observed by a Hermes session responding to a "network still running
like shit" report — NOT caused by that session's pod-removal action, since
this fingerprint predates it by hours (same as the two blackouts above).**
Timeline: ~19:07-19:18 pve01/02/03, both Mac Studios (.47=m4-2, .48=m4-1),
HA (.2), frigate (.85), lb-01 (.86), and even the SG105E (.15) all went dark
(ICMP 100% loss, TCP timeouts) simultaneously; tailscale's WireGuard reached
macstudio-m4-2 mid-window only after 1.8-5s (vs normal <50ms) — severe loss,
not a clean media disconnect for that host. ~19:20: SG105E, Netgear (.51),
HA, frigate, lb-01, and tailscale-gw all recovered to clean 0% loss, but
pve01/02/03 and both Studios stayed dark. ~19:24-19:26: the Netgear switch's
OWN management IP (.51) went dark again too — the blast radius widened back
out rather than narrowing to "just the downstream hosts". No SSH access was
obtained to any pve node or Studio during the whole window, so no
dmesg/`last`/pvecm read for this occurrence (unlike the ~14:50 event's clean
"crash"+fsck evidence). The Nest main unit's own uptime counter ticked
monotonically the entire time (two API reads ~9 min apart) — the Nest itself
never rebooted, ruling it out as the origin. **Leading candidates, still
unconfirmed:** (a) a shared power source (strip/UPS) for the
Netgear+PVE+Studios corner browning out/cycling — consistent with the
switch's OWN mgmt plane going dark, which a pure switch-port/NIC fault
wouldn't explain; (b) the already-flagged Netgear port 5 / pve01 100M-vs-
1000Mb negotiation mismatch, if it's actually flapping the whole port group
under some trigger. Next occurrence: physically check that corner's power
strip/UPS indicator and the switch's link LEDs, and grab host telemetry the
moment SSH access returns.

**LEADING THEORY as of ~19:31, user-supplied, NOT yet physically confirmed:**
the basement pod may be wired INLINE (WAN-in from the trunk switch, LAN-out
continuing to the under-work-desk switch branch) rather than as a leaf —
contradicting this doc's "pods hang off the trunk switch as leaves" diagram
above, which may be wrong for this specific pod. If so, a pod pulled from
the mesh via the Google Home app (not power-cycled) very plausibly stops
bridging its WAN<->LAN ports entirely, which would explain the sustained
(25+ min, non-recovering) blackout of everything behind it as a clean
single-point-of-failure — matches the documented "never place a pod inline"
pitfall exactly. Gap in this theory: at ~19:31 the SG105E (.15) itself — the
first hop directly off the Nest, upstream of where the basement pod is
believed to sit — also went dark, which a pod inline only between the trunk
and under-desk switches should NOT cause. Either the pod is physically
positioned closer to the Nest than believed (between the Nest and the
SG105E), or the Nest's own wired LAN port is separately flapping since the
topology change. Verification step (physical, cheap): count the ethernet
cables plugged into the basement pod — 2 (both WAN and LAN populated) all
but confirms inline-bridge; 1 means it's a normal leaf and not the cause.
Fix if confirmed: unplug both cables from the dead pod and run one cable
directly between whatever was upstream and whatever was downstream of it,
removing the pod from the physical path entirely (leave it unplugged/idle
afterward, don't re-add as a leaf without deciding on backhaul first).

| Device | Model | LAN IP | Notes |
| :--- | :--- | :--- | :--- |
| `netgear-switch-01` | GS108Ev4 (GS108E-400NAS) | `192.168.86.51` (verified live 2026-09-25; resolves as `gs108ev4.lan`) | 8-port "Easy Smart" managed switch. No SSH/SNMP/API — CGI web-form config only. MAC `28:94:01:77:1d:80` confirmed on-device. Find it by hostname/MAC — older notes listed `.62` and `.14`, both STALE. Managed via `ansible/roles/netgear_gs108ev4/` + `ansible/manage_netgear_switch.yml`. |

**Password state (2026-09-25):** the factory-default label password is
REJECTED — the user rotated it. The 1Password item `Netgear GS108Ev4`
holds the CURRENT password (verified working for a scripted read-only
login 2026-09-25). Caveat from experience: this switch allows only a few
concurrent HTTP sessions, each held until timeout — keep scripted logins
to ONE per investigation, and check `/login.cgi` for "maximum number of
sessions" BEFORE attempting a login.

**Loop prevention: OFF (user, 2026-09-25; re-verified OFF via the API).**
It had been reporting what the manual documents as a loop detect ("both
LEDs of a port blink at a constant speed"). Disabling it produced no
storm — verified host-side from macstudio-m4-1 (normal packet rates, 0%
loss, ~2 ms to gateway) and at the BGW (0 Tx/Rx errors, only port 2
live). Re-enable from DIAGNOSTICS → LOOP PREVENTION only if loop reports
recur.

**Status (2026-08-04):** switch reachable at `192.168.86.62` via a DHCP
reservation (added directly in AdGuard, not yet mirrored into the Ansible
role). Port mapping confirmed via live link-toggle tests (bring interface
down/up on each host, watch for the corresponding port's traffic counters
on `/portStatistics.cgi` to freeze — NOT via UP/DOWN status labels, which
are unreliable on macOS since `ifconfig down` only sets an administrative
flag and doesn't reliably drop the physical PHY link; Linux's
`ip link set down` / `networksetup -setnetworkserviceenabled ... off` do
drop the real link and are trustworthy for this test):

| Port | Device | Confirmed via |
| :--- | :--- | :--- |
| 8 | **Uplink toward the under-desk switch** (i.e. every host on this switch's other branches reaches the house through here) | Traffic test 2026-09-25: downloads to BOTH Mac Studios in turn (served from the MacBook on the desk branch) both produced by far the largest counter deltas on port 8, while no single other port carried a studio's whole flow. Matches user's recollection that 8 is the upstream to the under-work-desk switch. Also the port whose LEDs were seen blinking — a loop report landing on the uplink is the expected place for it. |
| 3 | `pve03` (192.168.86.13) | `ip link set nic0 down`, kernel dmesg `NIC Link is Down`, 2x clean repeat |
| 4 | `pve02` (192.168.86.12) | same method, 1x clean |
| 5 | `pve01` (192.168.86.11) | same method, 2x clean (1st attempt had a false negative from too-coarse SSH polling — use ≥1.5s poll interval and a ≥10s down window) |
| — | **Ports 6 and 7 are DARK (no link) as of 2026-09-25.** Port 7 previously held a Mac Studio; no studio is directly attached there now — the studios' traffic reaches this switch via port 8 / the desk branch. Do not assume the older 7/8 = two-studios mapping still holds. | dashboard + counter sampling 2026-09-25 |

**IMPORTANT CORRECTION:** an earlier version of this doc (same day) claimed
both Mac Studios were confirmed NOT on this switch, based on
`networksetup -setnetworkserviceenabled Ethernet off/on` toggle tests
showing zero effect on any port counter. That conclusion was **wrong** —
a physical cable-unplug test immediately afterward showed both Mac Studios
ARE on this switch (ports 7 and 8). Lesson: `networksetup ... off` is
**not reliable enough for this test either** — like `ifconfig down`, it
does not reliably drop the physical PHY link on these Mac Studios (Apple
Silicon / Thunderbolt-adjacent NIC hardware may power-manage the PHY
differently than the e1000e-based Proxmox NICs, where the same class of
test DID correlate correctly via kernel dmesg `NIC Link is Down`). For
Mac hardware, only a genuine physical unplug is trustworthy for this kind
of port-mapping test — do not trust `ifconfig down` or `networksetup off`
as a proxy for "physical link down" on macOS, on any NIC.

QoS mode note: the switch's QoS page defaults to **802.1P/DSCP** mode,
which reads priority from tags already inside packets — useless here since
Proxmox/replication traffic isn't tagged that way. **Port-based** mode is
the correct choice for prioritizing ports 3/4/5 directly regardless of
packet contents; switching QoS Mode to Port-based should expose a Priority
tab. As of 2026-08-04 this hasn't been applied — see "Root cause found and
fixed" below; QoS is now considered a secondary belt-and-suspenders step,
not the primary fix. Login password was changed by the user and stored in
1Password (no longer the factory default) — I no longer have programmatic
access to this switch.

### Root cause found and fixed (2026-08-04): synchronized replication bursts

The original throughput-dip investigation (2026-08-03) suspected shared-
uplink contention between Proxmox sync traffic and other LAN traffic.
Confirmed via VictoriaMetrics `node_network_transmit_bytes_total{device=
"vmbr0"}` query_range across pve01/02/03: multiple daily events where
**all 3 nodes simultaneously spike to a combined 100+ MB/s (800+ Mbps)**
on their LAN-facing interface for 4-5 minutes at a stretch (e.g. observed
20-46 MB/s per node, all 3 nodes, at the same timestamps).

Root cause: `/etc/pve/replication.cfg` had 20 replication jobs on a
`schedule *:N/15` pattern (offsets 0-14) — but 20 jobs into only 15 minute
slots meant 5 collisions where two jobs fire in the same minute, each
already rate-limited to 15 MB/s but stacking when combined. This is a
pmxcfs-managed live cluster file, NOT Ansible-templated — no repo drift
risk, but also nothing to update in `ansible/` for this fix.

**Fix applied:** rewrote the schedule to `*:N/20` with N assigned 0-19
sequentially per job (one job per unique minute in a 20-minute cycle
instead of a 15-minute one) — zero collisions, verified
`sort(schedules) == [0..19]` before applying. Backup saved on pve03 at
`/etc/pve/replication.cfg.bak-<timestamp>`. Applied by writing the new
config directly (no `pvesr` CLI edit-by-edit needed since it's one file);
`pvescheduler.service` re-reads `replication.cfg` from pmxcfs each cycle,
no restart required.

**Verified:** post-fix, max single-node vmbr0 throughput over a 15-minute
window was ~15 MB/s (down from a confirmed 50 MB/s pre-fix peak), with
zero timestamps where 2+ nodes simultaneously exceeded 20 MB/s (versus
multiple confirmed multi-node collision windows pre-fix). Root cause
resolved without touching the switch at all.

- `172.16.0.1` is `tailscale-gw` — both the SDN VNet gateway and the Tailscale subnet router advertising `172.16.0.0/24` over Tailscale. CTs on `private` use it as their default route only when they need outbound to non-LAN destinations.
- `10.99.0.3` is `tailscale-gw` eth2 on the `bwt` bridge — same CT (101) carries the BWT-lab subnet router, advertising `10.99.0.0/24` over Tailscale.
- MTU on `private` and `bwt` is 1450 (1500 minus VXLAN overhead — `net_private_mtu` / `net_bwt_mtu` in `ansible/group_vars/all/vars.yml`).

## PVE Sync network (VLAN 20, 172.20.0.0/24) — isolated corosync + replication

Built 2026-08-04 alongside the replication-schedule root-cause fix, as a
belt-and-suspenders layer: corosync/replication traffic is now on its own
L2 segment, physically confined to switch ports 3/4/5, invisible to every
other device on the LAN (no gateway, not routed, Google Home/Nest Wifi
Pro never sees it exist). Same physical wire as the LAN (each pve node has
only one NIC) so this does NOT add bandwidth capacity — the replication-
schedule fix already solved the bandwidth-contention problem; this adds
isolation on top.

**Switch side:** Advanced 802.1Q VLAN mode, VLAN 20 "pve-sync" created,
ports 3/4/5 set Tagged (T) for VLAN 20 while staying Untagged/PVID=1 for
the default LAN VLAN (confirmed via PVID Table: ports 3/4/5 show `1*, 20`,
all other ports show `1*` only). Every other port is Excluded (E) from
VLAN 20 entirely.

**Proxmox side (`/etc/network/interfaces` on each node):**
```
auto vmbr0
iface vmbr0 inet static
	address 192.168.86.1X/24
	gateway 192.168.86.1
	bridge-ports nic0
	bridge-stp off
	bridge-fd 0
	bridge-vlan-aware yes
	bridge-vids 20          # REQUIRED -- without this, vmbr0.20 exists but nic0
	                        # never egresses tagged VLAN 20 frames; symptom is
	                        # `bridge vlan show dev nic0` listing only vlan 1,
	                        # ping/ssh across the VLAN just times out silently.

auto vmbr0.20
iface vmbr0.20 inet static
	address 172.20.0.1X/24   # .11=pve01, .12=pve02, .13=pve03, no gateway
```

**Firewall (`/etc/pve/firewall/cluster.fw`):** Proxmox's cluster firewall
is enabled with default-deny-style rules gated on trusted IPSETs — adding
the VLAN alone isn't enough, traffic gets silently dropped unless
explicitly allowed. Added:
```
[IPSET pve_sync_vlan]
172.20.0.11
172.20.0.12
172.20.0.13

IN ACCEPT -source +pve_sync_vlan -p udp -dport 5405 -log nolog # corosync
IN ACCEPT -source +pve_sync_vlan -p tcp -dport 22 -log nolog   # ZFS replication (SSH transport)
```
Scoped narrowly (just corosync + SSH, not a broad subnet-wide ACCEPT) per
user preference, since isolation is the whole point of this network.

**Replication traffic redirect (`/etc/pve/datacenter.cfg`):**
```
replication: secure,network=172.20.0.0/24
```
This is the actual Proxmox-native mechanism (`man pvesr`, NETWORK section)
for repointing replication traffic onto a dedicated network — no per-job
config needed, applies cluster-wide immediately.

**Corosync:** NOT yet added as a second ring (`link1`) on this network —
still single-ring on the LAN (`link0`). This is the one remaining piece
**Corosync: added as a second ring, DONE and verified (2026-08-04).**
`link1` added on the isolated VLAN with `knet_link_priority` set so it's
preferred over the LAN (`link0`) — corosync actively uses the isolated
link, LAN stays configured as automatic failover only.

`/etc/pve/corosync.conf` changes (config_version bumped 3→4):
```
nodelist {
  node {
    name: pve01
    ...
    ring0_addr: 192.168.86.11
    ring1_addr: 172.20.0.11     # added
  }
  ... (same pattern for pve02/pve03)
}

totem {
  ...
  interface {
    linknumber: 0
    knet_link_priority: 5      # LAN — lower priority, failover only
  }
  interface {
    linknumber: 1
    knet_link_priority: 10     # VLAN 20 — higher priority, preferred
  }
  ...
}
```

**Apply mechanism note (corrected from an earlier wrong assumption):**
the documented Proxmox pattern is NOT "write to `corosync.conf.new` and
pmxcfs auto-swaps it" — that file sitting on disk does nothing on its own.
The actual mechanism (per `man pvecm`) is: copy to `.new`, edit `.new`,
then explicitly `mv corosync.conf.new corosync.conf` yourself. That `mv`
is what pmxcfs picks up and hot-applies to the running corosync cluster-
wide, no restart needed. Backup the working config first regardless
(`cp corosync.conf corosync.conf.bak`).

**Verified priority actually works (not just configured):** raw packet
counts from a short tcpdump window were NOT a reliable signal (passive-
mode keepalives on the non-primary link created noise). The real proof:
`corosync-cmapctl -m stats` per-link byte counters, diffed over a ~60s
window post-change — `link0.tx_data_bytes` delta was exactly 0 (fully
idle) while `link1.tx_data_bytes` grew by ~2.75MB in the same window.
`corosync-cfgtool -s` / `-n` on all 3 nodes confirmed both links enabled
+ connected to every peer. `pvecm status` confirmed `Quorate: Yes, Nodes: 3`
before, during, and after the corosync.conf swap — zero disruption.

## PVE Migrate network (VLAN 21, 172.21.0.0/24) — live migration, 2026-09-28

Second isolated VLAN on the **same physical ports 3/4/5** as the sync network
above, for live-migration traffic + its node-to-node SSH transport. Referenced
by `/etc/pve/datacenter.cfg` (`migration: secure,network=172.21.0.0/24`) and
allowed by the `pve_migrate_vlan` IPSET in `cluster.fw` (TCP 22 only).

**History — a codification gap that silently broke HA for 17 days.** This was
hand-configured on the nodes in Aug 2026 (memory fact 1174: "VLAN 21 … ALREADY
configured and live on all 3 PVE nodes' vmbr0.21"), but unlike VLAN 20 it was
never added to `roles/proxmox_network/templates/interfaces.j2` — `vmbr0.21`
appears in **no** git commit. The datacenter.cfg + firewall half was codified
(`73e52fb`), the interface half was not.

On **2026-09-11 13:39:23** a `deploy_proxmox.yml` run re-rendered
`/etc/network/interfaces` from that template on all three nodes (sub-second
apart = one run; its stated purpose was the vzdump backup-job fix). Nothing
warns on a template that omits a hand-added block, so `vmbr0.21` was deleted
with no error. The Aug-4 backup file is byte-identical to the post-Sep-11
file — that is the proof.

**Symptom:** every HA auto-rebalance migration aborted in ~1s with
`could not get migration ip: no IP address configured on local node for network
'172.21.0.0/24'`. HA's fallback is **stop → failed migrate → start**, i.e. it
restarts the guest on the same node anyway. Migrations succeeded through
Sep 10 (last OK: `qmigrate:200` 2026-09-07 21:33, `vzmigrate:104` 2026-09-10
18:10); from Sep 11 on, all failed — 24 on pve03, 16 on pve02. Guests bounced
with no node failure involved: authentik 20×, vm-01 4×, plus 101/102/103/105/108.
Confirmed live on 2026-09-28 21:41 for ct:106 (`auto rebalance - relocate ct:106
to pve01` → `migration failed (exit code 1)` → `vzshutdown` → `vzstart`).

**Fix (2026-09-28, deployed + verified):** codified the migrate VLAN in the
repo so no future playbook run can drop it again —
`net_pve_migrate_vlan_id: 21` + `net_pve_migrate_vlan_range` in
`group_vars/all/vars.yml`, `pve_migrate_vlan_ip` per-node in
`inventory/proxmox.yml`, and a `vmbr0.21` block (plus `21` on the required
`bridge-vids` line) in `interfaces.j2`. Applied via `update_network.yml`;
`vmbr0.21` up on all 3 nodes, `bridge vlan show dev nic0` lists 20 **and** 21,
and the exact previously-failing `pvecm mtunnel … -get_migration_ip` call now
returns the correct IP on all six node pairs.

**Switch side — VERIFIED 2026-09-28.** VLAN 21 is present and ports 3/4/5 pass
it: an SSH test bound to each node's `vmbr0.21` address reached both peers over
`172.21.0.x` from all six node pairs, which is only possible if the switch is
forwarding tagged VLAN 21 frames between ports 3/4/5. (The switch UI's VLAN page
(`/vlan.cgi`) exposes no config in its HTML — it loads the PVID table over
JS/XHR — so the CLI cannot read the VLAN mode; the traffic test is the stronger
evidence anyway. `vlanMod value="0"` in the page source is the *uncommitted
form default*, not the running mode: with `noVlan` actually active, no tagged
VLAN would pass at all.)

Note that VLAN 21 shares the **same** physical wires as VLAN 20 on ports 3/4/5,
so a migration cannot add LAN-visible load — which is also why the failure above
never disturbed VLAN 1 / the rest of the LAN.

## Proxmox nodes (dual-homed)

pve hosts are on the LAN by default; `roles/pve_private_ip/` adds a static
IP on the `private` SDN bridge so they have a private-subnet source IP for
Alloy push to vm-01:8428. Inbound on `private` is dropped via the
`PRIVATE-MONITORING-IN` iptables user chain — pve management stays
LAN-only despite the L3 endpoint on the SDN.

| Host    | LAN IP          | Private IP    | Notes                           |
| :------ | :-------------- | :------------ | :------------------------------ |
| `pve01` | `192.168.86.11` | `172.16.0.2`  | Proxmox cluster member          |
| `pve02` | `192.168.86.12` | `172.16.0.3`  | Proxmox cluster member          |
| `pve03` | `192.168.86.13` | `172.16.0.4`  | Proxmox cluster member          |

Source: `ansible/inventory/proxmox.yml` + `roles/pve_private_ip/defaults/main.yml`.

## Service CTs (private subnet)

| Hostname        | VMID | Private IP       | LAN IP (if any)    | Role                                        |
| :-------------- | :--- | :--------------- | :----------------- | :------------------------------------------ |
| `authentik`     | 100  | `172.16.0.20`    | -                  | SSO / OIDC provider                         |
| `tailscale-gw`  | 101  | `172.16.0.1`     | `192.168.86.16` (static) | SDN VNet gateway + Tailscale subnet router  |
| `dns-01`        | 102  | `172.16.0.10`    | -                  | Bind9 authority for `chi.lab.amd-e.com`     |
| `lb-01`         | 103  | `172.16.0.30`    | DHCP (`192.168.86.x`) | Nginx L7 reverse proxy                  |
| `mail-01`       | 104  | `172.16.0.40`    | -                  | Postfix → iCloud SMTP relay                 |
| `ntp-01`        | 105  | `172.16.0.11`    | -                  | Chrony, syncs against `time.nist.gov`       |
| `vm-01`         | 106  | `172.16.0.42`    | DHCP (`192.168.86.x`) | VictoriaMetrics + blackbox + Loki + Alloy   |
| `graf-01`       | 107  | `172.16.0.41`    | -                  | Grafana + image renderer                    |
| `proxy-01`      | 108  | `172.16.0.12`    | -                  | Squid caching proxy                         |
| `adblock-proxy-01` | 118 | `172.16.0.49`  | -                  | mitmproxy explicit HTTPS proxy for personal-device Discord ad-stripping (Tailscale-only ingress, joins tailnet directly like hermes-gw-01) |

`172.16.0.40` was previously assigned to **both** `mail-01` and `vm-01` (ARP race). Resolved 2026-05-01 — moved `vm-01` to `.42`. See commit `12bb4c2`.

## Monitoring & metrics ingestion into VictoriaMetrics (vm-01)

Three independent paths feed vm-01, covering different layers:

- **Alloy (pull-replaced push agent)** — runs on every managed host
  (LXCs, VMs, the pve nodes themselves). Ships generic Debian/RHEL
  node_exporter-shape host metrics + journal logs via
  `prometheus.remote_write` / `loki.write` to vm-01/Loki. See
  `ansible/roles/alloy/`.
- **Direct Prometheus scrape** — `prometheus.yml.j2` on vm-01 itself
  scrapes a handful of targets that don't run Alloy: Home Assistant
  (`/api/prometheus`), the exo inference cluster (both Mac Studios,
  `:52415/metrics`), Tanium appliances (dedicated hardened
  `tanium_node_exporter` role), and blackbox-driven HTTPS/TCP probes.
  See `ansible/roles/victoriametrics/templates/prometheus.yml.j2`.
- **Proxmox native metric export (added 2026-08-04)** — pvestatd (the
  daemon that already feeds the Proxmox GUI's RRD graphs every 10s) is
  registered as an InfluxDB v2 client pointed at vm-01's native
  `/api/v2/write` endpoint. Gets node + per-guest (VM/CT) CPU/mem/disk/net
  that Alloy's generic host metrics don't cover (Alloy on a pve node only
  sees the pve host's own OS, not neighboring guests). Config lives in
  `/etc/pve/status.cfg` (pmxcfs, cluster-wide, write-once) via
  `ansible/roles/pve_metrics_export/` (id `vm-01-influx`), invoked from
  `deploy_monitoring.yml`'s "Register Proxmox's native metric export"
  play. Series land prefixed by VictoriaMetrics' Influx line-protocol
  mapping (`system_cpu`, `ballooninfo_free_mem`, `cpustat_avg1`, etc.),
  labeled `object` (`node`/`qemu`/`lxc`), `vmid`, `host`, `nodename`.
  Verify: `curl http://172.16.0.42:8428/api/v1/series?match[]=system_cpu`.
  Deliberately does NOT cover storage-pool usage, HA resource state,
  replication job status/duration, or backup job status — pvestatd's
  native export doesn't expose those.
- **prometheus-pve-exporter (added 2026-08-04, same day)** — pulled the
  layer the native export above doesn't carry. Python venv service on
  vm-01 (`ansible/roles/pve_exporter/`, port 9221), scraping the Proxmox
  API via a dedicated read-only token (`pve-exporter@pve`, PVEAuditor
  role, vaulted as `vault_pve_exporter_token_id`/`_secret` — NOT the
  full-privilege `root@pam!hermes-automation` token used elsewhere).
  Scrape config in `roles/victoriametrics/templates/prometheus.yml.j2`
  (job `pve_exporter`), one target per pve node by its ACME FQDN (so
  `verify_ssl: true` actually validates). Gets
  `pve_replication_duration_seconds` /
  `pve_replication_last_sync_timestamp_seconds` /
  `pve_replication_failed_syncs` (replication job status/duration),
  `pve_ha_state` (HA resource state), `pve_not_backed_up_info` /
  `pve_not_backed_up_total` (backup job coverage), and
  `pve_disk_usage_bytes{id=~"storage/.*"}` / `pve_disk_size_bytes`
  (storage pool usage) — directly usable for alerting on the 2026-08-04
  replication-burst root-cause fix and the frigate HA node-affinity
  rule. Verify: `curl http://172.16.0.42:8428/api/v1/query?query=up{job="pve_exporter"}`.
- **windows_exporter (added 2026-08-04, same day) — BUILT, NOT YET
  DEPLOYED** — closes the remaining gap: the Windows VMs
  (`win-sql-01`/`win-ts-01`/`win-tms-01`/`win-tzs-01`, VMIDs 250-253,
  see "VMID conventions" below) run neither Alloy (its install role has
  no Windows package logic) nor anything else, so they had zero
  in-guest metrics — only the hypervisor-level view from
  `pve_metrics_export`/`pve_exporter` above. `ansible/roles/windows_exporter/`
  installs `prometheus-community/windows_exporter` via WinRM
  (`ansible/deploy_windows_exporter.yml`), baked into the golden
  Windows Server template build (`ansible/docs/windows_template_guide.md`
  step "E") so future clones ship with it pre-installed. Scrape config
  in `prometheus.yml.j2` (job `windows_exporter`) reads from
  `windows_exporter_scrape_targets` — currently empty, since all 4 VMs
  are powered off with no assigned static IP. **Next step once these
  VMs are turned back on:** assign static IPs (see "VMID conventions"
  below — none currently allocated), run `deploy_windows_exporter.yml`
  against each, populate `windows_exporter_scrape_targets` in
  `roles/victoriametrics/defaults/main.yml`, redeploy
  `deploy_monitoring.yml --limit victoriametrics`.
- **Alloy metrics-only mode for media_ingest/media_ingest_02/media_gallery
  (added 2026-08-05)** — closes the last real gap: these 3 CTs run a
  secondary-source scraper/gallery pipeline deliberately obfuscated in
  this public repo (`vault_media_ingest_02_scraper_pkg`,
  `_scrape_usernames`, telethon private-chat detail — see
  `roles/media_ingest_02_host` and the `git-history-identity-scrub`
  skill), so they were fully excluded from Alloy 2026-07-27 through
  2026-08-04 to keep that detail out of the shared Loki instance —
  meaning zero perf visibility on them the whole time. Fixed by adding
  `alloy_ship_logs: false` (per-host `vars:` in `inventory/proxmox.yml`,
  see `roles/alloy/README.md` "Metrics-only hosts") — the template
  conditionally drops the entire `loki.source.journal`/`loki.write`
  block when set, so ONLY the `prometheus.exporter.unix` block (CPU/
  mem/disk/net counters, no process names, no command-lines, no
  journal content) ships. Verified live 2026-08-05: `up{job=
  "node_exporter",instance=~"media-ingest.*|tg-harvester.*"}`==1 for
  all 3, AND `curl .../loki/api/v1/label/host/values` confirmed to
  carry zero entries for any of them before or after the change. Also
  fixed a real (pre-existing, unrelated) inventory bug found along the
  way: `gallery-01`'s `ansible_host` used the private-subnet IP with
  the default jump-host `ProxyCommand`, which times out for this CT
  specifically since it joined the tailnet directly (renamed from
  `tg-harvester-01`, see warm memory fact 397) — added a per-host
  override to reach it via its real tailnet IP (100.83.114.12)
  directly, no jump.
- **Upgraded to unit-allowlist log shipping (same day, 2026-08-05,
  later)** — user asked specifically about log shipping (not just
  metrics) for these 3 hosts. Audited actual `journalctl` output on all
  3 live boxes before deciding anything (not guessing from unit names):
  confirmed the scraper/collector/gallery service units genuinely log
  sensitive content on nearly every line (media-ingest-02.service logs
  the literal scrape-target username on every INFO line;
  media-ingest-collector.service logs chat IDs + person/folder names;
  media-gallery-*.service logs folder/person names + rclone remote
  paths) — `alloy_ship_logs: false` (all-or-nothing) stays correct for
  those units specifically. But ssh/cron/postfix/systemd-journald carry
  zero sensitive content and ARE useful signal (ssh brute-force
  attempts, cron failures, mail delivery issues) — so upgraded from the
  blunt `alloy_ship_logs: false` to `alloy_log_unit_allowlist` (see
  `roles/alloy/README.md` "Unit-allowlist log shipping"): a
  `loki.relabel` `action = "keep"` rule inside Alloy itself drops any
  journal entry whose unit doesn't match the allowlist regex, before it
  ever leaves the box — not a server-side Loki filter applied after the
  fact. Hit and fixed a real River (Alloy config language) syntax bug
  along the way: double-quoted strings need `\\.` for a literal
  backslash in a regex, easy to get wrong when templating from a plain
  Jinja var — switched to backtick-quoted raw strings (River's
  recommended pattern for regexes) so the value renders verbatim.
  Verified live per-host via direct Loki queries (not just "looks
  fine"): confirmed the 4 sensitive units
  (media-ingest-collector.service, media-ingest-02.service,
  media-gallery-gallery.service, media-gallery-upload.service) return
  `totalLinesProcessed: 0` in Loki — zero lines ever landed — while
  `ssh`/`ssh@*`/`cron` units ARE present with real, safe content (SSH
  session audit trail, no sensitive detail).

## Tanium cluster

| Hostname  | VMID | Private IP       | Role                  |
| :-------- | :--- | :--------------- | :-------------------- |
| `ts-01`   | 200  | `172.16.0.51`    | Tanium Server         |
| `ts-02`   | 201  | `172.16.0.52`    | Tanium Server         |
| `tms-01`  | 202  | `172.16.0.53`    | Tanium Module Server  |
| `tms-02`  | 203  | `172.16.0.54`    | Tanium Module Server  |
| `tzs-01`  | 204  | `172.16.0.55`    | Tanium Zone Server    |
| `tzs-02`  | 205  | `172.16.0.56`    | Tanium Zone Server    |

## BWT lab (bandwidth-throttle repro)

Separate from the existing `tanium_cluster` — uses TanOS appliance VMs on the
isolated `bwt` SDN VNet (`10.99.0.0/24`, VLAN 200). 1× TS + 4× ZS for the
server side; LXC clients for the load drivers. See
`inventory/proxmox.yml` under `bwt_lab` and the `tanium-bandwidth-throttle`
skill for context. Pre-staged Tanium RPMs land in `files/tanium-<version>/`
(gitignored) via `scripts/tanium/fetch_artifactory_bundle.sh`.

Network isolation: the `bwt` subnet is intentionally walled off from the
`private` subnet (172.16.0.0/24) by pve01's `PRIVATE-MONITORING-IN` firewall.
BWT hosts can reach the internet via SNAT through pve01 (10.99.0.1) but
cannot reach `dns-01`, `vm-01`, etc. — BWT uses Cloudflare/Google DNS pushed
by `bwt-dhcp`. Ansible reaches BWT VMs via ProxyJump through pve01.

| Hostname     | VMID | BWT IP                  | Role                              |
| :----------- | :--- | :---------------------- | :-------------------------------- |
| `bwt-dhcp`   | 114  | `10.99.0.2` (static)    | dnsmasq DHCP server (Debian LXC)  |
| `bwt-ts`     | 220  | `10.99.0.10` (static)   | Tanium Server (TanOS)             |
| `bwt-zs-01`  | 221  | `10.99.0.11` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-02`  | 222  | `10.99.0.12` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-03`  | 223  | `10.99.0.13` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-zs-04`  | 224  | `10.99.0.14` (static)   | Tanium Zone Server (TanOS)        |
| `bwt-tc-01`  | 320  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-02`  | 321  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-03`  | 322  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-04`  | 323  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-05`  | 324  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-06`  | 325  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-07`  | 326  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |
| `bwt-tc-08`  | 327  | `10.99.0.50-250` (DHCP) | BWT test client (LXC)             |

DHCP pool: 10.99.0.50–250 (12h lease). 10.99.0.1 is the gateway (pve01),
10.99.0.2 is `bwt-dhcp` (this server), 10.99.0.10–14 are reserved for the
five TanOS servers (excluded from DHCP because TanOS sets static IP at
install time via kickstart).

## Tanium clients (test endpoints)

VMIDs 300-313, IPs `172.16.0.60–73`. See `inventory/proxmox.yml` under `tanium_clients`.

## VMID conventions

- **100–113** — core service CTs (authentik, dns-01, ntp-01, etc.)
- **115–118** — personal/media service CTs (gallery-01, media-ingest-01/02, adblock-proxy-01)
- **114** — BWT lab service CTs (`bwt-dhcp`)
- **200–219** — existing `tanium_cluster` placeholders (ts-01/02, tms-01/02, tzs-01/02)
- **220–249** — BWT lab TanOS VMs (`bwt-ts`, `bwt-zs-01..04`)
- **250–253** — Windows test VMs (win-sql-01, win-ts-01, win-tms-01, win-tzs-01)
- **300–319** — existing `tanium_clients` LXC endpoints
- **320–339** — BWT lab LXC clients (`bwt-tc-01..NN`)
- **400+** — reserved / ad-hoc test VMs (e.g. 400 = Some-Other-ECF-Testing)
- **9000-9999** — Proxmox templates (9000=Windows Server 2022, 9001=TanOS 1.8.6 fresh-install, 9002=TanOS 1.8.6 BWT-ready)

## Where IPs are defined (in order of authority)

1. **`ansible/group_vars/all/vars.yml`** — `ip_*` vars are the canonical
   source for the 9 core service CTs:
   `ip_dns_primary`, `ip_ntp_server`, `ip_proxy`, `ip_authentik`,
   `ip_loadbalancer`, `ip_mail_server`, `ip_grafana`, `ip_vm`,
   `ip_tailscale_gw`. Plus `ip_homeassistant` (the off-cluster HA host
   on the LAN that hosts AdGuard for DoT upstream + iOS push). Same
   file also defines `net_private_*` (SDN: range/gw/bridge/mtu) and
   `net_lan_*` (range, gateway).
2. **`ansible/inventory/proxmox.yml`** — every host's `ansible_host:`.
   For the 9 core CTs, this is templated as `"{{ ip_<name> }}"`, so
   `vars.yml` and inventory can't drift. Tanium hosts (cluster +
   clients) and the pve LAN IPs are inlined here directly because
   nothing else needs to consume them as vars.
3. **`ansible/roles/pve_private_ip/defaults/main.yml`** — pve hosts'
   private-subnet IPs (`pve_private_ip_map`).

When the `ip_*` var doesn't match the inventory's `ansible_host` (as
happened with vm-01/mail-01 before the consolidation), bad things
happen silently. The current pattern keeps them in lockstep.

## Adding a new CT

1. Pick a free IP in the appropriate range (check this file).
2. Pick a free VMID (next sequential within the convention range).
3. Add an `ip_<name>` entry to `ansible/group_vars/all/vars.yml`.
4. Add the host to `ansible/inventory/proxmox.yml` with
   `ansible_host: "{{ ip_<name> }}"`, plus `vmid` and `target_node`.
5. If the CT belongs to the private subnet, ensure it's a member of the
   `private_subnet` parent group in `proxmox.yml` (directly or via a
   child group) so it inherits the work-MacBook ProxyCommand.
6. Update this file with the new allocation.
