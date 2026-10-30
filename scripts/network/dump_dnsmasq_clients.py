#!/usr/bin/env python3
"""dump_dnsmasq_clients.py -- list every DHCP client from the HA dnsmasq add-on's
live table (ws://192.168.86.2:8976/ws) and flag Netgear OUIs."""
import json
import sys

import websocket

NETGEAR_OUIS = {"00:14:6c", "00:1b:2f", "00:24:b2", "08:36:c9", "10:da:43", "20:4e:7f", "28:c6:8e",
                "2c:30:33", "3c:37:86", "44:94:fc", "4c:60:de", "6c:b0:ce", "84:1b:5e", "9c:3d:cf",
                "a0:40:a0", "a4:2b:8c", "b0:39:56", "b0:7f:b9", "c0:3f:0e", "c4:04:15", "cc:40:d0",
                "d4:6e:0e", "dc:ef:09", "e0:46:9a", "e4:f4:c6", "e8:4e:84", "f8:73:94", "a0:63:91",
                "e0:91:f5", "b0:95:8e", "10:0d:7f", "2c:44:fd", "bc:a5:11", "38:94:ed", "9c:c9:eb",
                "a4:2b:b0", "3c:52:82", "08:02:8e", "34:98:b5"}

ws = websocket.create_connection("ws://192.168.86.2:8976/ws", timeout=15)
data = {}
for _ in range(10):
    msg = ws.recv()
    try:
        d = json.loads(msg)
    except ValueError:
        continue
    if d.get("current_clients"):
        data = d
        break
ws.close()

clients = data.get("current_clients", [])
print(f"clients in the dnsmasq table: {len(clients)}")
if not clients:
    print("no client list received; raw:", str(data)[:300])
    sys.exit(1)

rows = []
for c in clients:
    lease = c.get("lease", {})
    mac = (lease.get("mac_addr") or "").lower()
    rows.append((lease.get("ip_addr", ""), mac, lease.get("hostname") or "-",
                 c.get("has_static_ip"), (c.get("friendly_name") or "")[:24]))
rows.sort(key=lambda r: tuple(int(x) for x in r[0].split(".")) if r[0] else (0,))
for ip, mac, host, static, friendly in rows:
    flag = "   <== NETGEAR" if mac[:8] in NETGEAR_OUIS else ""
    print(f"  {ip:16} {mac:18} {host:26} static={str(static):5} {friendly}{flag}")
