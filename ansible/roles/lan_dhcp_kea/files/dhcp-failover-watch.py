#!/usr/bin/env python3
"""DHCP failover for the Kea pair when the built-in HA hook will not promote.

Kea 2.4.1's HA hook on this pair never lets the backup serve: with the primary
gone it stays in "backup" state, `dhcp-enable` returns success but the socket is
still filtered, and `ha-maintenance-start` refuses (backup -> partner-in-maintenance).

So the promotion is done at the unit level instead: this watchdog probes the
primary's control port and, after N consecutive failures, swaps in the standalone
config (same subnet/pool/reservations, HA hook removed) and restarts Kea, which
then serves normally. When the primary answers again it swaps the HA config back
and restarts, handing the service over.

State is kept in /run so a reboot starts clean; on any run where the primary is
alive the HA config is restored, which also undoes a half-finished promotion
after a power cut.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

PRIMARY = "192.168.86.4"
SELF = "192.168.86.5"
PORT = 8000
FAILS_TO_PROMOTE = 3
OKS_TO_DEMOTE = 2
CONF = "/etc/kea/kea-dhcp4.conf"
HA_CONF = "/etc/kea/kea-dhcp4.ha.conf"
STANDALONE_CONF = "/etc/kea/kea-dhcp4.standalone.conf"
STATE = "/run/dhcp-failover.state"
LOG = "/var/log/dhcp-failover.log"
UNIT = "kea-dhcp4-server"


def log(msg):
    with open(LOG, "a") as fh:
        fh.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg))


def primary_alive():
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((PRIMARY, PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def serving_standalone():
    try:
        with open(CONF) as fh:
            return "libdhcp_ha.so" not in fh.read()
    except OSError:
        return False


def load():
    try:
        with open(STATE) as fh:
            return json.load(fh)
    except Exception:                       # noqa: BLE001
        return {"fails": 0, "oks": 0, "serving": serving_standalone()}


def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)


def swap(src, why):
    subprocess.run(["cp", "-a", src, CONF], check=True)
    rc = subprocess.run(["systemctl", "restart", UNIT]).returncode
    log("%s: %s -> %s (restart rc=%d)" % (why, os.path.basename(src), CONF, rc))
    return rc == 0


def main():
    state = load()
    if primary_alive():
        state["fails"] = 0
        state["oks"] += 1
        if serving_standalone() or state.get("serving"):
            if state["oks"] >= OKS_TO_DEMOTE and swap(HA_CONF, "primary back"):
                state["serving"] = False
    else:
        state["oks"] = 0
        state["fails"] += 1
        if not serving_standalone() and state["fails"] >= FAILS_TO_PROMOTE:
            if swap(STANDALONE_CONF, "primary unreachable x%d" % state["fails"]):
                state["serving"] = True
    save(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
