#!/usr/bin/env python3
"""
Bridge a local TCP port to a Proxmox VE VNC console over its authenticated
WSS vncwebsocket endpoint, so tools like vncdotool (which only speak raw
RFB/TCP) can drive a VM's console through Proxmox's proxy.

Usage: pve_vnc_bridge.py <vmid> <node> <local_port> [password_file]

Requires env vars PVE_API and PVE_AUTH (same as pve_exec.sh, source
~/.config/proxmox-lab/env first).

Password handling: Proxmox vncproxy tickets/passwords are short-lived and
effectively single-use. This script pre-fetches a ticket BEFORE accepting
the next local connection and writes the matching RFB password to
password_file (default /tmp/pve_vnc_password.txt) so a calling script can
read it and hand it to vncdo -p before/while connecting.
"""
import asyncio
import json
import os
import ssl
import subprocess
import sys
import urllib.parse

import websockets


def get_vncproxy_ticket(api, auth, node, vmid):
    # The Proxmox API is intermittently flaky (empty/timeout responses even
    # when otherwise healthy) -- retry a few times before giving up.
    last_err = None
    for attempt in range(5):
        try:
            resp = subprocess.run(
                ["curl", "-sk", "-m", "10", "-X", "POST", "-H", auth,
                 f"{api}/nodes/{node}/qemu/{vmid}/vncproxy", "-d", "websocket=1"],
                capture_output=True, text=True, timeout=15,
            )
            data = json.loads(resp.stdout)["data"]
            return data
        except Exception as e:
            last_err = e
            print(f"vncproxy ticket fetch attempt {attempt+1} failed: {e}",
                  file=sys.stderr)
    raise RuntimeError(f"vncproxy ticket fetch failed after retries: {last_err}")


async def bridge(vmid, node, local_port, password_file):
    api = os.environ["PVE_API"]
    auth = os.environ["PVE_AUTH"]
    host = api.split("//", 1)[1].split("/", 1)[0]

    header_name, header_value = auth.split(":", 1)
    extra_headers = {header_name.strip(): header_value.strip()}

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    # Pre-fetch the first ticket before accepting any connection.
    ticket_data = get_vncproxy_ticket(api, auth, node, vmid)
    with open(password_file, "w") as f:
        f.write(ticket_data["password"])
    print(f"Ticket fetched, password written to {password_file}: "
          f"{ticket_data['password']}", file=sys.stderr)

    async def handle_client(reader, writer):
        nonlocal ticket_data
        ws = None
        last_err = None
        for attempt in range(6):
            port = ticket_data["port"]
            ticket = ticket_data["ticket"]
            ws_url = (
                f"wss://{host}/api2/json/nodes/{node}/qemu/{vmid}/vncwebsocket"
                f"?port={port}&vncticket={urllib.parse.quote(ticket, safe='')}"
            )
            try:
                ws = await websockets.connect(
                    ws_url,
                    additional_headers=extra_headers,
                    ssl=ssl_ctx,
                    max_size=None,
                    open_timeout=15,
                    proxy=None,
                )
                break
            except Exception as e:
                last_err = e
                print(f"[attempt {attempt+1}] connect failed: {e}", file=sys.stderr)
                # ticket burned by the failed attempt -- refetch and update
                # the password file so a waiting caller re-reads the right one
                ticket_data = get_vncproxy_ticket(api, auth, node, vmid)
                with open(password_file, "w") as f:
                    f.write(ticket_data["password"])
                await asyncio.sleep(1)
        if ws is None:
            print(f"giving up: {last_err}", file=sys.stderr)
            writer.close()
            return

        try:
            async with ws:
                print("WS connected", file=sys.stderr)

                async def ws_to_tcp():
                    try:
                        async for msg in ws:
                            if isinstance(msg, str):
                                msg = msg.encode()
                            writer.write(msg)
                            await writer.drain()
                    except Exception as e:
                        print("ws_to_tcp ended:", e, file=sys.stderr)

                async def tcp_to_ws():
                    try:
                        while True:
                            data = await reader.read(65536)
                            if not data:
                                break
                            await ws.send(data)
                    except Exception as e:
                        print("tcp_to_ws ended:", e, file=sys.stderr)

                await asyncio.gather(ws_to_tcp(), tcp_to_ws())
        except Exception as e:
            print("client handler error:", e, file=sys.stderr)
        finally:
            writer.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", local_port)
    print(f"Local TCP bridge listening on 127.0.0.1:{local_port}", file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    vmid, node, local_port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    password_file = sys.argv[4] if len(sys.argv) > 4 else "/tmp/pve_vnc_password.txt"
    asyncio.run(bridge(vmid, node, local_port, password_file))
