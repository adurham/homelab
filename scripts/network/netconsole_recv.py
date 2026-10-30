#!/usr/bin/env python3
"""netconsole_recv.py -- UDP receiver for Linux netconsole streams.

Runs on a host that is expected to stay up (here: pve03) and collects the kernel
messages that sibling nodes emit over netconsole. This matters because the pve
nodes' journald is volatile (RAM-only), so anything logged between "the network
stops" and "the machine resets" is lost -- netconsole gets those lines off the
box *before* the link dies, with the sender's own kernel timestamps.

Every datagram is appended to LOG with a receive-side timestamp, mirrored into
the system journal (tag "netconsole") so it also reaches Loki, and the file is
kept under MAX_BYTES by rolling one generation.

Deliberately dependency-free (stdlib only) and passive: it never sends anything,
never touches the senders, and stopping the unit is harmless.
"""
import os
import socket
import sys
import syslog
import time

PORT = 6666
# /var/log, not /root: the unit runs with ProtectHome=yes so /root is read-only,
# and ProtectSystem=full leaves /var writable.
LOG = "/var/log/netconsole.log"
MAX_BYTES = 32 * 1024 * 1024
ROLL = LOG + ".1"

def roll():
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) >= MAX_BYTES:
            os.replace(LOG, ROLL)
    except OSError:
        pass

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    syslog.openlog("netconsole", syslog.LOG_KERN, syslog.LOG_INFO)
    syslog.syslog(syslog.LOG_INFO, f"receiver listening on udp/{PORT}, log={LOG}")
    with open(LOG, "a", buffering=1) as fh:
        fh.write(f"# netconsole receiver started {time.strftime('%Y-%m-%d %H:%M:%S%z')}\n")
        while True:
            try:
                data, addr = sock.recvfrom(65535)
            except OSError as e:
                syslog.syslog(syslog.LOG_ERR, f"recvfrom failed: {e}")
                time.sleep(1)
                continue
            roll()
            stamp = time.strftime("%Y-%m-%d %H:%M:%S%z")
            for line in data.decode("utf-8", "replace").splitlines():
                if not line.strip():
                    continue
                entry = f"{stamp} {addr[0]} {line}"
                fh.write(entry + "\n")
                syslog.syslog(syslog.LOG_INFO, entry)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
