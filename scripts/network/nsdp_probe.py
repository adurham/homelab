#!/usr/bin/env python3
"""nsdp_probe.py -- ask any Netgear Easy-Smart switch on this L2 to identify itself.

NSDP (Netgear Switch Discovery Protocol) is the broadcast protocol the vendor
utility uses; unlike the web UI it does not depend on the switch's IP being known.
An answer proves the switch's CPU is alive even when http://<ip>/ is unreachable.

Sends several plausible request shapes to the broadcast addresses and prints any
response (with the responder's IP and a hex dump), so a guessed field layout can
still be recognised.
"""
import binascii
import socket
import struct
import time

PORTS = (63323, 63322)
TARGETS = ("255.255.255.255", "192.168.86.255")

# version 1, op 1 = read request, reserved; then TLVs. Variants cover the field
# layouts seen in public implementations (END tag, 0xffff end, bare header,
# explicit port-status tag).
VARIANTS = [
    b"\x01\x01\x00\x00\x00\x00\x00\x00",
    b"\x01\x01\x00\x00\xff\xff\x00\x00",
    b"\x01\x01\x00\x00",
    b"\x01\x01\x00\x00\x00\x00\x00\x00\x0b\x00\x00\x00",
]

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.settimeout(0.5)
sent = 0
for port in PORTS:
    for tgt in TARGETS:
        for pkt in VARIANTS:
            try:
                s.sendto(pkt, (tgt, port))
                sent += 1
            except OSError as e:
                print(f"send failed to {tgt}:{port}: {e}")
print(f"sent {sent} probe datagrams to ports {PORTS}")

deadline = time.time() + 6
replies = []
while time.time() < deadline:
    try:
        data, addr = s.recvfrom(4096)
    except socket.timeout:
        continue
    replies.append((addr, data))
    print(f"REPLY from {addr[0]}:{addr[1]}  {len(data)} bytes: {binascii.hexlify(data[:160]).decode()}")

if not replies:
    print("no NSDP reply (switch CPU did not answer any variant)")
else:
    for addr, data in replies:
        # first TLV usually starts after the 4-byte header
        print(f"--- decode {addr[0]}: header={binascii.hexlify(data[:4]).decode()} first-tlv={binascii.hexlify(data[4:12]).decode()}")
