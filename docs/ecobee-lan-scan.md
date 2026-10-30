# Ecobee is continuously ARP-scanning the home LAN

**Status:** open, forked out of the pve self-fence investigation (2026-10-30). Not harmful to the
lab — parked here so it has its own session and does not pollute the switch/stall work.

## What it does (measured 2026-10-30 13:33, capture from the Mac on the same L2)

Device: **192.168.86.113**, MAC **44:61:32:df:66:47**.

- OUI `44:61:32` = **ecobee inc**. Home Assistant's registry
  (`/config/.storage/core.entity_registry` on the HAOS host) lists that IP as a HomeKit accessory
  (`"AccessoryIP": "192.168.86.113"`), so it is a thermostat paired through HA's HomeKit integration.
- **3,847 ARP requests in 58 s ≈ 67 requests/second**, covering **249 distinct addresses** — the whole
  of `192.168.86.0/24` — on a repeat period of about **3.7 seconds per full sweep**. That is roughly
  **340,000 ARP requests per hour**, ~15× the next-chattiest device on the LAN (the Google router).
- Alongside the sweep it sends mDNS queries for **`_d2d._tcp.local`** (~0.6/s) — i.e. it is also looking
  for a peer *service* that never answers. That plus the endless full-subnet sweep is the signature of a
  stuck discovery loop, not of normal operation.
- It deliberately skips a small set of addresses in the sweep; the observed skips in this window were
  `.41 .43 .56 .65 .93 .104 .113` (own address plus six others). Worth understanding — it suggests the
  sweep targets a *list* it maintains rather than a blind range walk.

Reproduce: `sudo tcpdump -i <lan-if> -n 'ether src 44:61:32:df:66:47' | head` and count lines per second.

## Why it is NOT the cause of the pve stalls

Broadcast rate matters in the thousands-per-second range before it disturbs a switch; 67/s is noise, and
it sweeps like this through perfectly healthy periods. It is real traffic pollution for captures and
pcap-based work on this LAN, and it makes this device useless as a quiet neighbour — nothing more.

## Candidates, cheapest first

1. **Power-cycle the thermostat** (its own menu, or its breaker) — the standard cure for a wedged
   discovery loop. Re-measure the rate afterwards; if it stays low, done.
2. **Check the firmware version** and whether ecobee has an update for it (thermostat: Settings → About;
   or the device attributes in HA). A known-bad firmware that loops local discovery is a plausible root.
3. **Look at HA's side**: Loki (`{host="homeassistant"}`) and the recorder DB for HomeKit/ecobee errors,
   repeated re-pairing, or `unavailable` flapping. A stale/broken HomeKit pairing is the most likely
   trigger for the `_d2d` searching — if HA's HomeKit pairing with it is half-dead, re-pairing is the fix
   (and that is a smart-home change, so ask before doing it).
4. **Contain it** only if it persists after 1-3: separate SSID/VLAN for the thermostat. That is a
   network change on the live LAN and needs the owner's explicit go-ahead first.

## Notes for whoever picks this up

- Do not touch the lab's switch/VLAN/DHCP config for this; the pve self-fence lane owns those changes.
- The lab monitors already watch this MAC: `mac-flow-witness.service` on pve01/02/03 counts its frames
  per second alongside the node MACs (`/root/mac_flow.log`), so if the sweep rate ever changes shape —
  or spikes at the same instant a node stalls — it is already recorded.
