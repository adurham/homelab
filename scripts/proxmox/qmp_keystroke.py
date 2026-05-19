#!/usr/bin/env python3
"""Drive a Proxmox VM keyboard via QMP send-key over the local QMP socket.

Used for automation that needs to interact with a VM at the BIOS/EFI or pre-SSH
console level — specifically driving TanOS appliance initial-config wizards
where ansible can't reach yet (no IP, no SSH keys). Run on a Proxmox host
that owns the VM (the QMP socket is at /var/run/qemu-server/<vmid>.qmp).

Usage: python3 qmp_keystroke.py <vmid> <action> [<arg>] [<action> [<arg>]] ...

Actions:
  type <text>          — type literal text (newline = ret, tab = tab)
  key <qcode>          — send a single qcode like "ret", "spc", "tab", "esc"
  combo <qcode>+...    — send a key combo like "ctrl+c", "shift+a"
  sleep <seconds>      — pause (float OK)
  screen <path>        — screendump to .ppm at path

Example:
  python3 qmp_keystroke.py 220 \\
    type "tanadmin\\n" sleep 1 type "MyPassword\\n" sleep 3 \\
    screen /tmp/screen.ppm

This file lives in scripts/proxmox/ because it's a Proxmox-side helper, not
a Tanium-side one. The ansible roles/tanos_vm_clone/ copies it to /tmp on
the relevant pve node before running it.
"""
import json
import socket
import sys
import time

SOCK = f"/var/run/qemu-server/{sys.argv[1]}.qmp"

# Map ASCII char -> (modifiers, qcode). Letters lowercase, no modifier; uppercase letter -> shift modifier.
# Numbers and "common" symbols on US keyboard.
QKEY = {
    " ":"spc", "\n":"ret", "\t":"tab",
    "`":"grave_accent","-":"minus","=":"equal","[":"bracket_left","]":"bracket_right",
    "\\":"backslash",";":"semicolon","'":"apostrophe",",":"comma",".":"dot","/":"slash",
}
SHIFT_QKEY = {
    "~":"grave_accent","!":"1","@":"2","#":"3","$":"4","%":"5","^":"6","&":"7","*":"8","(":"9",")":"0",
    "_":"minus","+":"equal","{":"bracket_left","}":"bracket_right","|":"backslash",
    ":":"semicolon","\"":"apostrophe","<":"comma",">":"dot","?":"slash",
}

def connect():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK)
    s.settimeout(3)
    s.recv(4096)  # banner
    s.send(b'{"execute":"qmp_capabilities"}\n')
    s.recv(4096)
    return s

def send_key(s, keys):
    """keys = [qcode1, qcode2, ...] sent as one keypress (combo)"""
    payload = {"execute":"send-key","arguments":{"keys":[{"type":"qcode","data":k} for k in keys]}}
    s.send((json.dumps(payload)+"\n").encode())
    # Best-effort ACK drain — QMP responds async and we don't care about
    # the reply here, only that the bytes were written. socket.timeout is
    # the expected case when the host is slow; OSError covers everything
    # else short of a dropped socket.
    try:
        s.recv(4096)
    except (socket.timeout, OSError):
        pass

def type_text(s, text, delay=0.04):
    for ch in text:
        keys = None
        if ch == "\n":
            keys = ["ret"]
        elif ch == "\t":
            keys = ["tab"]
        elif ch == " ":
            keys = ["spc"]
        elif ch.isalpha():
            if ch.isupper():
                keys = ["shift", ch.lower()]
            else:
                keys = [ch]
        elif ch.isdigit():
            keys = [ch]
        elif ch in QKEY:
            keys = [QKEY[ch]]
        elif ch in SHIFT_QKEY:
            keys = ["shift", SHIFT_QKEY[ch]]
        else:
            continue
        send_key(s, keys)
        time.sleep(delay)

def screenshot(s, path):
    payload = {"execute":"screendump","arguments":{"filename":path}}
    s.send((json.dumps(payload)+"\n").encode())
    time.sleep(0.5)
    try:
        s.recv(4096)
    except (socket.timeout, OSError):
        pass

s = connect()
i = 2
while i < len(sys.argv):
    action = sys.argv[i]
    i += 1
    if action == "type":
        type_text(s, sys.argv[i])
        i += 1
    elif action == "key":
        send_key(s, [sys.argv[i]])
        i += 1
    elif action == "combo":
        send_key(s, sys.argv[i].split("+"))
        i += 1
    elif action == "sleep":
        time.sleep(float(sys.argv[i]))
        i += 1
    elif action == "screen":
        screenshot(s, sys.argv[i])
        i += 1
    else:
        print(f"unknown: {action}", file=sys.stderr)
        sys.exit(1)
s.close()
