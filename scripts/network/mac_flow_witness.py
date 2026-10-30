#!/usr/bin/env python3
"""mac_flow_witness.py -- per-second frame counts for chosen source MACs, for the
pve self-fence investigation.

WHY: on 2026-10-30 the pve nodes repeatedly lose ALL network reachability in one
instant (witness: every probe dies inside 5 s) while their NIC carrier stays up and
nothing reaches the journal. The open question is WHERE the datapath stops: in the
victim's NIC, in its cable/switch port, or upstream. The victim's own counters
(nic_stall_watch.sh) answer "is it still receiving"; this answers the other half
from a neighbour's vantage point: "are the victim's frames still ARRIVING on a
switch port that is otherwise healthy?".

  victim still transmitting (frames seen here) while it cannot receive anything
  -> the path victim->LAN is alive, the RX direction (or the victim's RX) is not.
  victim silent here too -> its TX/port/whole datapath stopped.

Writes one line per second to the log:  <iso> <mac>=<frames_s> ...  (only MACs
with a non-zero count are printed, plus a heartbeat line every 60 s). Rotates at
MAXB. Read-only observer: a single AF_PACKET socket, no packets are modified.

Usage: mac_flow_witness.py -i nic0 -m 70:b5:e8:53:58:67 -m d0:8e:79:04:15:b6 [-o /root/mac_flow.log]
"""
import argparse
import os
import socket
import sys
import time
from datetime import datetime, timezone

MAXB = 1048576
HEARTBEAT_S = 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--iface", default="nic0")
    ap.add_argument("-m", "--mac", action="append", required=True,
                    help="source MAC to count (repeatable)")
    ap.add_argument("-o", "--out", default="/root/mac_flow.log")
    ap.add_argument("-n", "--name", action="append", default=[],
                    help="label for each -m, same order (optional)")
    a = ap.parse_args()

    macs = {}
    for idx, m in enumerate(a.mac):
        raw = bytes.fromhex(m.replace(":", "").replace("-", ""))
        label = a.name[idx] if idx < len(a.name) else m
        macs[raw] = label
    if len(a.name) and len(a.name) != len(a.mac):
        print("each -m needs a matching -n", file=sys.stderr)
        sys.exit(2)

    def rotate():
        try:
            if os.path.exists(a.out) and os.path.getsize(a.out) > MAXB:
                os.replace(a.out, a.out + ".1")
        except OSError:
            pass

    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    s.bind((a.iface, 0))
    s.settimeout(0.5)

    counts = {raw: 0 for raw in macs}
    rotate()
    with open(a.out, "a", buffering=1) as fh:
        fh.write(f"mac_flow_witness started on {a.iface}: "
                 + " ".join(f"{lab}={raw.hex(':')}" for raw, lab in macs.items()) + "\n")
        last = time.time()
        last_hb = time.time()
        while True:
            try:
                frame = s.recv(2048)
            except socket.timeout:
                frame = None
            except OSError:
                time.sleep(0.1)
                frame = None
            if frame and len(frame) >= 14:
                src = frame[6:12]
                if src in counts:
                    counts[src] += 1
            now = time.time()
            if now - last >= 1.0:
                ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
                if any(counts.values()):
                    fh.write(ts + " " + " ".join(f"{macs[r]}={c}" for r, c in counts.items() if c) + "\n")
                    counts = {raw: 0 for raw in macs}
                    fh.flush()
                elif now - last_hb >= HEARTBEAT_S:
                    fh.write(f"{ts} (no frames from watched MACs)\n")
                    fh.flush()
                    last_hb = now
                last = now
            if os.path.getsize(a.out) > MAXB:
                rotate()


if __name__ == "__main__":
    main()
