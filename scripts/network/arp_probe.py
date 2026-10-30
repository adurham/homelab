#!/usr/bin/env python3
"""arp_probe.py -- find devices that live outside our subnet, at the frame level.

A raw ARP request needs no IP address in the target subnet: we put whatever sender
IP we like in the request and listen for replies. That lets a host on 192.168.86.0/24
discover a switch sitting at its factory default (typically 192.168.0.239 - a subnet
with no route from here, so every ordinary probe fails silently) without adding an
interface address or changing any configuration.

usage: arp_probe.py <iface> <sender-ip> <target-ip> [<target-ip> ...]
       arp_probe.py nic0 192.168.0.23 192.168.0.239 192.168.0.100
"""
import binascii
import socket
import struct
import sys
import time

IFACE, SENDER_IP = sys.argv[1], sys.argv[2]
TARGETS = sys.argv[3:]

ETH_P_ARP, ETH_P_ALL = 0x0806, 0x0003
BCAST = b"\xff\xff\xff\xff\xff\xff"


def mac_of(ip):
    return bytes.fromhex("020000000001")


def arp_request(sender_mac, sender_ip, target_ip):
    eth = BCAST + sender_mac + struct.pack(">H", ETH_P_ARP)
    arp = struct.pack(">HHBBH", 1, 0x0800, 6, 4, 1)
    arp += sender_mac + socket.inet_aton(sender_ip)
    arp += b"\x00" * 6 + socket.inet_aton(target_ip)
    return eth + arp


def main():
    try:
        iface_mac = open(f"/sys/class/net/{IFACE}/address").read().strip()
    except OSError as e:
        print(f"cannot read {IFACE} address: {e}")
        return
    src = bytes.fromhex(iface_mac.replace(":", ""))
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    s.bind((IFACE, 0))
    s.settimeout(0.05)
    for t in TARGETS:
        try:
            s.send(arp_request(src, SENDER_IP, t))
        except OSError as e:
            print(f"send failed for {t}: {e}")
    print(f"sent {len(TARGETS)} ARP requests from {IFACE} claiming {SENDER_IP}")

    seen, deadline = {}, time.time() + 5
    while time.time() < deadline:
        try:
            frame = s.recv(2048)
        except socket.timeout:
            continue
        if len(frame) < 42 or frame[12:14] != b"\x08\x06":
            continue
        op = struct.unpack(">H", frame[20:22])[0]
        if op != 2:            # only replies
            continue
        mac = ":".join(f"{b:02x}" for b in frame[22:28])
        ip = socket.inet_ntoa(frame[28:32])
        seen[ip] = mac

    if not seen:
        print("no ARP replies (nothing answers in that range)")
    for ip, mac in sorted(seen.items(), key=lambda kv: tuple(int(x) for x in kv[0].split("."))):
        print(f"  {ip:16} {mac}")


if __name__ == "__main__":
    main()
