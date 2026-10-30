# Ecobee ARP sweep + `_d2d` browse: what drives them

**Status:** root-caused as far as this LAN allows (2026-10-30, two sessions). The HomeKit pairing is
healthy and unimplicated. The `_d2d` browse is now explained and falsified as the sweep's cause; the ARP
sweep's driver is still unidentified and **no lever available from the house side stops it**. Nothing was
left changed.

Device: **192.168.86.113**, MAC **44:61:32:df:66:47**, mDNS host **`ecobee-ares.local`**, model **ECB601**
(Smart Thermostat Premium), firmware **4.10.80392** built **Sep 3 2026**, AirPlay deviceID
`39:B1:5C:22:7A:F9`.

## The two behaviours (re-measured 13:48–14:22)

**1. ARP sweep — the unsolved one.**
2,400 ARP requests in 40 s ≈ **60/s** covering **251 distinct addresses** (all of `192.168.86.0/24` bar
itself), *randomised* order, full sweep every ~4 s. The skip set is not stable between windows, so there
is no maintained target list. Its shape is a **scheduled census on a fixed timer** — it runs at the same
rate regardless of what the LAN answers or what is changed — not a stuck retry loop. That is why a
power-cycle is unlikely to clear it (consistent with every owner report).

**2. `_d2d._tcp` browse — now explained.**
`_d2d._tcp.local` is the **only** mDNS question this device ever asks (15 / 80 / 15 question packets
across three captures; no other service type). It asks ~0.5/s forever, with none of the RFC 6762 backoff
a conformant browser would apply.

**A/B proof that it is a "wait until a peer answers" need:**
- Advertise a throwaway peer — `dns-sd -R d2d-probe _d2d._tcp local 17120` — and the thermostat's
  `_d2d` questions go to **0 in 40 s**.
- Tear the advertisement down and they resume at **0.57/s (26 in 45 s)**.
- It did **not** open a connection to the advertised port (0 TCP packets to 17120) — the announcement
  alone satisfies it.

So `_d2d` is ecobee-private device-to-device peer discovery. This house has one thermostat and no other
ecobee equipment, so the peer it wants has never existed here. What the peer *is* (second thermostat,
ecobee camera/doorbell, the app on the LAN) stays unknown — a generic probe like the above satisfies the
browse but is not a peer the device will talk to.

## `_sideplay._tcp` identified: it is the AirPlay/AirTunes receiver

- Port **7100** answers `HTTP/1.1 404 … Server: AirTunes/366.0`.
- `GET /info` returns an AirPlay plist: `protocolVersion 1.1`, `sdk AirPlay;2.6.1`,
  `PTPInfo PTP-AirPlay;2.6.1`, `sourceVersion 366.0`, `model ECB601`, `manufacturer ecobee Inc.`,
  `firmwareRevision 4.10.80392`, `statusFlags 1028 (0x404)`, `name 39:B1:5C:22:7A:F9` with
  `nameIsFactoryDefault 0` — i.e. its AirPlay name is still the raw device ID and was never given a
  proper name.
- The Sony HT-A5000's ordinary `_airplay._tcp` advertises `srcvers=366.0` too, confirming the family.
- `_sideplay._tcp` is also what **HA's own ecobee (cloud) integration** keys on for LAN discovery —
  HA core commit #62335 "Add zeroconf discovery to ecobee for non-homekit models" maps
  `_sideplay._tcp` + `mdl: eb-*|ecobee*` → ecobee. So it is ecobee's LAN presence service generally, not
  unique to this model.

## The HomeKit pairing is NOT broken

Entry `01JWBHM9X5MWW0EPGZPPY9ZPTT` (pairing id `D7:ED:06:1B:9A:75`, AccessoryIP .113, AccessoryPort
37663): loaded; all ~170 entities available; zero homekit_controller errors; debug logging for 75 s shows
only the periodic update and `async_set_available_state True` — no connection-lost, no reconnect churn,
no re-pairing. Events push into HA; **writes round-trip** (mute off→on→off, and the AirPlay switch
on→off). Exactly one pairing. Watchdog silent since 2026-10-02.

HAP accessories never search for their controller, so a stale pairing cannot cause device-side
discovery hunting anyway. Re-pairing was not done and is not indicated.

## Ruled out by measurement (each was a live test, not an assumption)

| Candidate | Test | Result |
|---|---|---|
| Stale/broken HomeKit pairing | live HAP read + event + write, one pairing, no churn | healthy — not the cause |
| The AirPlay enable flag | `switch.…_airplay_enable` on 45 s, then off | sweep 72 → 60 → 68/s, browse unchanged — no effect |
| The missing `_d2d` peer | synthetic `_d2d` peer advertised, sweep re-measured | sweep unchanged at 67.7/s — **not** a peer-hunt fallback |
| A zone-controller hunt | `sensor.ecobee_edgewater_road_use_zone_controller` | `False` — nothing being hunted |
| Cloud/WAN trouble | cloud-side sensors current (≤1.5 min) | fine |
| The Sep 24–30 pairing flaps | flaps stopped while the sweep continues | unrelated |
| HA-side mDNS loop | HA never browses `_d2d`; nothing in HA references it | not HA |

## Can it be stopped? Not from inside the house today

- **No vendor setting exists.** Multi-year owner reports (r/Ubiquiti "Ecobee – Constant ARP requests",
  MikroTik forum) describe the identical sweep across several 4.x firmwares with no exposed option; the
  thermostat's own exposed settings show nothing peer- or scan-related.
- **Isolation would cost the integration.** Google Nest Wifi has no VLANs; the only isolation is the guest
  network, which breaks LAN visibility to HA — i.e. loses the HomeKit integration. Not acceptable.
- **Answering `_d2d` silences only the browse**, not the sweep, and only while a responder runs — a
  permanent fake-peer daemon is a mitigation, and mitigations are not wanted here.
- Switch-level broadcast rate-limiting would be a mitigation, is another lane's territory, and needs
  approval.
- Remaining untested device-side options are all the owner's: a power-cycle (low odds, see above) and
  checking for a firmware update. Reporting the packet evidence to ecobee support is the only route to an
  actual fix, since they own the firmware.

## Also found / open

- **`sf=0` inconsistency.** The ecobee's `_hap._tcp` TXT
  (`c#=138 ff=33 id=D7:ED:06:1B:9A:75 md=ECB601 pv=1.1 s#=835 sf=0 ci=9 sh=… fe=1`) advertises **status
  flag = not paired** while the healthy Lutron Smart Bridge 2 advertises `sf=1`. HA works around it (its
  zeroconf discovery matches the existing entry's unique_id and aborts). Accessory-side advertising
  defect; impact unproven; not worth a re-pair on this evidence.
- Do not port-scan this device: a high-rate SYN scan is reported to wedge the ecobee Wi-Fi SoC.
- Its `_sideplay` advertisement is sporadic (0 hits in two 150 s windows) and its `_hap._tcp` announcement
  rate is normal — *less* frequent than the Lutron bridge's. There is no advertisement storm.

## Reproduce

```
sudo tcpdump -i en0 -n -s 0 -w e.pcap 'arp or udp port 5353'            # then count per phase
dns-sd -L "Edgewater Road" _hap._tcp local                               # HAP TXT (note sf=0)
curl -s http://192.168.86.113:7100/info | plutil -convert xml1 -o - -    # AirPlay self-report
dns-sd -R d2d-probe _d2d._tcp local 17120                                # A/B: before/after browse rate
```

## Notes for whoever picks this up

- Do not touch the lab's switch/VLAN/DHCP config for this; the pve self-fence lane owns those changes.
- The lab monitors already watch this MAC: `mac-flow-witness.service` on pve01/02/03 counts its frames per
  second (`/root/mac_flow.log`), so a change in sweep shape would be recorded.
