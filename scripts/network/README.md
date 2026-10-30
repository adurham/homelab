# Network switch query scripts

Read-only config dumps for the two managed switches on the home LAN.
Both pull credentials from 1Password at call time via the `op` CLI —
nothing is stored on disk or in this repo.

| Script | Switch | IP | Notes |
|---|---|---|---|
| `query_netgear.py` | NETGEAR GS108Ev4 (8-port) | 192.168.86.51 | homelab switch (PVE nodes + Mac Studios). IP verified live 2026-09-25 (older notes said .14/.62 — stale). |
| `query_tplink.py`  | TP-Link TL-SG105E (5-port) | 192.168.86.15 | living-room switch, first hop off the Nest router |

Unmanaged switches (basement, upstairs game room) have no management plane
and are not queryable.

## Usage

```sh
python3 query_netgear.py                 # system + settings + ports
python3 query_netgear.py toggles         # just the on/off settings
python3 query_netgear.py ports           # just the port table
python3 query_netgear.py --backup out.bin  # binary config backup

python3 query_tplink.py                  # all sections
python3 query_tplink.py loop igmp        # only matching sections
python3 query_tplink.py --raw qos        # raw inline JS for a section
```

## 1Password items

Both live in the personal vault (`sxghbs2czadjbz76hh4jkssvb4`):

- **`Netgear GS108Ev4`** — PASSWORD-type item, password only (the switch
  login has no username field).
- **`TP-Link TL-SG105E`** — LOGIN-type item, `username` = `admin`.

Change the `OP_ITEM` constant at the top of each script if the titles change.

## Implementation notes / gotchas

These cost real time to work out; don't rediscover them.

### NETGEAR GS108Ev4

**Auth** (from `/login.js`): `POST /login.cgi` with field name `password`
set to `md5(merge(realPassword, rand))`, where `merge()` interleaves the two
strings character-by-character (`p0 r0 p1 r1 …`, leftovers appended). The
`rand` seed is on the login page as
`<input type=hidden id='rand' value='NNN'>` — note the **single-quoted and
bare attributes**, so a regex expecting double quotes silently fails.
Success returns a `SID` cookie.

**You must fetch `/index.cgi` immediately after login.** Without it every
later page returns a 303-byte `Redirect to Login` stub *even though the SID
cookie is valid*. This looks exactly like an auth failure and sends you
hunting for a JSON API that doesn't exist.

**State lives in the rendered HTML, not an API.** Toggles are plain
checkboxes — the presence of the `checked` attribute means enabled:

| Page | Checkbox id | Setting |
|---|---|---|
| `/loopDetection.cgi` | `loopPrevMod` | Loop Prevention |
| `/powerSaving.cgi` | `powStateModSet` | Power Saving |
| `/dos.cgi` | `dosState` | DoS Prevention |
| `/switchDiscovery.cgi` | `upnp_status` | Switch Discovery (NSDP) |
| `/leds.cgi` | `ledState` | Port LEDs |

**Session limit ≈ 3, held until timeout.** Rapid probing exhausts the slots
and login then fails with *"The maximum number of sessions has been
reached."* — which reads like someone else is logged in, but is usually your
own abandoned sessions. Always `GET /logout.cgi` in a `finally` block; the
script does this and backs off on contention.

**Port data** is all in `/dashboard.cgi` (~33 KB): one
`<li class="list_item index_li">` per port, with hidden inputs classed
`port`, `portName`, `LinkedSpeed`, `ingressRate`, `egressRate`, `flowCtr`,
`priority` (note the lowercase on the last four). The human-readable value is
the `<span>` **immediately before** each hidden input, not the input's own
`value` attribute. The status span is `text-success-1` *or* `text-success-2`
depending on link state — match `text-success-\d`.

**All UI labels are `mlNNN` i18n placeholder tokens**, so key off element
ids/classes and never off visible label text.

**Config backup**: `GET /confFile.cgi?cmd=backup_conf` returns a 5365-byte
binary with magic `NG`, model string at offset 4, and IP/mask/gateway at
0x41.

### TP-Link TL-SG105E

**Auth** is plaintext: `POST /logon.cgi` with `username`, `password`, and
`logon=Login`, returning an `H_P_SSID` cookie. There is no client-side
crypto despite `cryp_new.js` existing on the device.

**Page-name casing matters** — wrong casing closes the connection with no
response rather than 404ing:

```
/SystemInfoRpm.htm   /LoopPreventionRpm.htm  /PortSettingRpm.htm
/PortStatisticsRpm.htm  /IgmpSnoopingRpm.htm  (not IGMP)
/QosBasicRpm.htm     (not QoS)                /PortMirrorRpm.htm
/Vlan8021QRpm.htm    /VlanMtuRpm.htm          /PortTrunkRpm.htm
```

**State is in inline JS** in three shapes, all parsed by the script:

```js
var all_info = { state:[...], link_status:[...], pkts:[...] };  // object + arrays
var info_ds  = { descriStr:["TL-SG105E"], ... };                // object + strings
var pPri     = new Array(1,1,1,1,1);                            // bare Array()
```

The `pkts` array is flat, four entries per port:
`[txGood, txBad, rxGood, rxBad]`.

## Reachability witness (`lab_witness.sh` / `lab-witness.service`)

Not a switch config dump — a 1s-resolution TCP reachability witness deployed on
all three PVE nodes as the `lab-witness` systemd unit (log `/root/lab_witness.log`).
It exists to discriminate the recurring simultaneous-unclean-reboot
investigation: it records the per-second transition sequence (which peer/switch/WAN
target stops answering, and in what order) so a future event can be classified as
either a lab-branch power event or HA self-fencing. Besides the three PVE nodes
(TCP/22) and the two managed switches above (TCP/80), it probes the gateway
(`192.168.86.1`, ICMP) and `1.1.1.1:443` (WAN). See `docs/ipam.md` (EVENT
2026-09-30 / 2026-10-01) for how the logs are interpreted.

## Self-fence forensics (deployed 2026-10-30 on pve01/02/03)

Two read-only observers that catch the instant a node loses its network, plus why
the existing witness cannot answer the question by itself:

| Tool | Unit | Output | Answers |
|---|---|---|---|
| `nic_stall_watch.sh` | `nic-stall-watch.service` | `/root/nic_stall.log`, `/root/progress_witness.log` | Is the NIC still *receiving* while everything else is dead (1 s counter deltas), what did the driver say (dmesg ring buffer, live RAM), and was the *machine* still executing during the ~110 s before the reset (1 Hz fsync'd local progress trace, no network involved) |
| `mac_flow_witness.py` | `mac-flow-witness.service` (+ `/etc/default/mac-flow-witness`) | `/root/mac_flow.log` | Seen from a healthy neighbour: are the stalled node's frames still arriving on the wire (per-second counts per sibling node MAC) |

`lab_witness.sh` cannot answer either question: its `HB` line is emitted every **30 loop
iterations** and a fully-failed round costs ~7 s (7 probes x 1 s timeout), so no HB can
appear inside a 110 s outage — missing heartbeats during a stall are a cadence property,
not evidence that the box hung.

Install (per node; the unit reads `MAC_FLOW_ARGS` from `/etc/default/mac-flow-witness`):

```sh
sudo install -m 755 nic_stall_watch.sh /usr/local/sbin/nic_stall_watch.sh
sudo install -m 755 mac_flow_witness.py /usr/local/sbin/mac_flow_witness.py
sudo install -m 644 nic-stall-watch.service mac-flow-witness.service /etc/systemd/system/
echo 'MAC_FLOW_ARGS="-i nic0 -o /root/mac_flow.log -m <macB> -n pveB -m <macC> -n pveC"' \
  | sudo tee /etc/default/mac-flow-witness
sudo systemctl daemon-reload
sudo systemctl enable --now nic-stall-watch.service mac-flow-witness.service
```
