# Ecobee is continuously ARP-scanning the home LAN

**Status:** closed as *not a fault* (2026-10-30, second session). The sweep is the thermostat's own
firmware behaviour; the HomeKit pairing is fully healthy and is not implicated. No change made.

## What it does (re-measured 2026-10-30 13:48–14:03, tcpdump + dns-sd from the Mac on the same L2)

Device: **192.168.86.113**, MAC **44:61:32:df:66:47**, mDNS host **`ecobee-ares.local`**. OUI
`44:61:32` = ecobee inc; the accessory's own IPv6 EUI-64 (`4661:32ff:fedf:6647`) confirms the MAC.
Model **ECB601** (Smart Thermostat Premium), firmware **4.10.80392**.

- **2,400 ARP requests in 40 s ≈ 60 requests/second**, covering **251 distinct addresses** — the whole of
  `192.168.86.0/24` bar itself — so a full sweep roughly every **4 seconds**. Order is *randomised*, not
  sequential (`…194 .132 .37 .128 .109…`), i.e. a deliberate shuffled scan, not a range walk.
- The skip set is **not stable between windows** (13:33 run: `.41 .43 .56 .65 .93 .104 .113`; 13:48 run:
  `.113 .188 .55 .79 .84`). It always excludes its own address; the rest vary — so the "it targets a list"
  reading in the first version of this doc was a sampling artefact, not a maintained target list.
- It also multicasts mDNS **PTR queries for `_d2d._tcp.local`** at a steady **~0.5/s** (80 queries in
  150 s), over both IPv4 and IPv6. **Nothing on this LAN advertises `_d2d._tcp`** (`dns-sd -B _d2d._tcp`
  returns nothing), so the browse never resolves.
- It **advertises a private service `_sideplay._tcp.local`** (instance `ecobee-ares`, port 7100), TXT
  `id=D7:ED:06:1B:9A:75 f= mdl=ECB601 mfg=ecobee Inc. serialNumber=531626698442 v=366.0` — same id as its
  HAP pairing, `v=366.0` = the AirPlay 2 version string. Neither `_sideplay` nor `_d2d` is an Apple or
  Amazon type (`_hap`/`_airplay`/`_raop`/`_companion-link` vs `_amzn-wplay`); both look ecobee-private and
  are undocumented. **Do not assert what they are for.**
- Its `_hap._tcp` **announcement rate is normal** — one cache-flush announcement in a 150 s window, *less*
  often than the Lutron Smart Bridge 2 in the same window. There is no advertisement storm.

Reproduce:
```
sudo tcpdump -i <lan-if> -n 'ether src 44:61:32:df:66:47 and arp' | head          # count/s
sudo tcpdump -i <lan-if> -n -vv 'udp port 5353 and ether src 44:61:32:df:66:47'   # _d2d + _hap TXT
dns-sd -L "Edgewater Road" _hap._tcp local                                        # accessory TXT
```

## The HomeKit pairing is NOT broken (this retired the hypothesis in candidate 3)

Checked against the live HA instance (`homekit_controller` entry `01JWBHM9X5MWW0EPGZPPY9ZPTT`,
pairing id `D7:ED:06:1B:9A:75`, AccessoryIP .113, AccessoryPort 37663):

- Entry loaded; **all ~170 entities available**; **zero homekit_controller errors** in the core log.
- With debug enabled for 75 s: only the periodic device update and repeated `async_set_available_state
  True` — **no "connection lost", no reconnect churn, no re-pairing attempts**.
- The accessory **pushes characteristic events** to HA (motion/occupancy/humidity inside the last
  minute), and a **write round-trips**: `switch.edgewater_road_mute` off→on→off, HA reflecting the
  accessory's echo each time. Read, event and write paths all work.
- **Exactly one** homekit_controller pairing for this accessory.
- The self-heal watchdog has not fired since **2026-10-02** (28 days).

Mechanically the hypothesis was wrong anyway: in HAP the **controller** browses `_hap._tcp` and connects
to the accessory — an accessory never searches for its controller. And the ARP sweep is not mDNS-driven,
so an unreachable/stale pairing could not produce it. **Re-pairing would risk a working integration for
no benefit, so it was not done.**

## Findings that remain open / unexplained

- **`sf=0` inconsistency.** The ecobee's `_hap._tcp` TXT reads
  `c#=138 ff=33 id=D7:ED:06:1B:9A:75 md=ECB601 pv=1.1 s#=835 sf=0 ci=9 sh=…= fe=1` — i.e. **status flag =
  "not paired"** — while the Lutron Smart Bridge 2, also paired to HA and healthy, advertises **`sf=1`**.
  HA works around it (its zeroconf discovery matches the existing entry's unique_id and aborts), and this
  is measurable *right now*, so it is an accessory-side advertising defect, not a lost pairing. Impact
  unproven; not worth a re-pair on this evidence.
- **What `_d2d._tcp` is for** — unknown. If it is ecobee's device-to-device peer discovery, the plausible
  peers are a second ecobee, an ecobee camera/doorbell, or the ecobee app on the LAN. The ecobee account
  holds **one** thermostat and no other ecobee device, so there is no peer to find.

## Why it is harmless (perspective, unchanged from the first version)

Broadcast rate matters in the thousands-per-second range before it disturbs a switch; 60/s ≈ 30 kbps is
noise on wire and modest airtime on Wi-Fi. It is real pollution for pcap work on this LAN and nothing
more. It is **not** the cause of the pve self-fence events, and it is **not** the cause of the Sep 24–30
HomeKit pairing flaps either — the flaps stopped after the Sep 30 re-cable while the sweep continues.

## Ruled out as levers

- **Not the HomeKit pairing** — verified healthy above.
- **Not a stale/failed discovery on HA's side** — no HA-side mDNS or zeroconf loop; HA never browses
  `_d2d` and nothing in HA references it.
- **No vendor toggle found.** Multi-year owner reports (r/Ubiquiti "Ecobee – Constant ARP requests",
  MikroTik forum) describe the identical full-subnet sweep across several 4.x firmwares with no exposed
  setting and no vendor fix.
- **Containment would cost the integration.** On this network (Google Nest Wifi) there are no VLANs; the
  only isolation is the guest network, which breaks LAN visibility to HA — and with it the HomeKit
  integration. Do not recommend it without saying so.
- Do not port-scan this device to probe it: a high-rate SYN scan is reported to wedge the ecobee Wi-Fi
  SoC (IP stack dies, radio stays associated, needs a physical power cycle).

## Next attack vector, if the sweep ever needs to go

The one untested, falsifiable experiment: answer the `_d2d._tcp` browse with a synthetic responder and
re-measure the ARP rate. If the sweep stops, the sweep *is* the peer hunt (and the fix is to give it the
peer or stop it looking); if it continues, the two behaviours are confirmed independent. This feeds a
synthetic peer to a live HVAC thermostat, so it needs the owner's go-ahead first.

The upstream experiments nobody has published — disabling the thermostat's Alexa/Siri, one at a time,
re-measuring the sweep after each — are also unrun. Both are thermostat-side settings, so both are the
owner's actions.

## Notes for whoever picks this up

- Do not touch the lab's switch/VLAN/DHCP config for this; the pve self-fence lane owns those changes.
- The lab monitors already watch this MAC: `mac-flow-witness.service` on pve01/02/03 counts its frames
  per second alongside the node MACs (`/root/mac_flow.log`), so if the sweep rate ever changes shape —
  or spikes at the same instant a node stalls — it is already recorded.
