#!/usr/bin/env python3
"""Query the TP-Link TL-SG105E (192.168.86.15) config over HTTP.

Auth: plaintext POST of username/password to /logon.cgi -> H_P_SSID cookie.
Pages are server-rendered and embed their state in inline JS in three shapes:
    var all_info = { state:[...], link_status:[...] };   # object w/ arrays
    var info_ds  = { descriStr:["TL-SG105E"], ... };     # object w/ strings
    var pPri = new Array(1,1,1,1,1);                     # bare Array()
This parses all three.

Credentials come from 1Password at call time via `op` -- never stored on disk.

Usage:
    python3 query_tplink.py             # all sections
    python3 query_tplink.py loop qos    # only matching sections
    python3 query_tplink.py --raw igmp  # dump raw inline JS for a section
"""
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import http.cookiejar

HOST = "192.168.86.15"
OP_ITEM = "TP-Link TL-SG105E"

PAGES = [
    ("System Info",     "/SystemInfoRpm.htm"),
    ("Loop Prevention", "/LoopPreventionRpm.htm"),
    ("Port Settings",   "/PortSettingRpm.htm"),
    ("Port Statistics", "/PortStatisticsRpm.htm"),
    ("IGMP Snooping",   "/IgmpSnoopingRpm.htm"),
    ("QoS",             "/QosBasicRpm.htm"),
    ("Port Mirror",     "/PortMirrorRpm.htm"),
    ("VLAN 802.1Q",     "/Vlan8021QRpm.htm"),
    ("VLAN MTU",        "/VlanMtuRpm.htm"),
    ("Port Trunk/LAG",  "/PortTrunkRpm.htm"),
]

STATE = {0: "Disabled", 1: "Enabled"}
LINK = {0: "Link Down", 1: "Auto", 2: "10Half", 3: "10Full",
        4: "100Half", 5: "100Full", 6: "1000Full", 7: "-"}
PRIO = {0: "-", 1: "1 (Lowest)", 2: "2 (Normal)", 3: "3 (Medium)", 4: "4 (Highest)"}

# scalar -> (label, value map)
SCALARS = {
    "lpEn":             ("Loop Prevention",      STATE),
    "state":            ("IGMP Snooping",        STATE),   # inside igmp_ds
    "suppressionState": ("Report Suppression",   STATE),
    "qosMode":          ("QoS Mode",             {1: "Port-based", 2: "802.1P"}),
    "MirrEn":           ("Port Mirroring",       STATE),
    "MirrPort":         ("Mirror Dest Port",     None),
    "portNumber":       ("Port count",           None),
}
SKIP = {"tip", "port_middle_num", "max_port_num", "index", "i", "count"}


def op_get(item, field):
    r = subprocess.run(["op", "item", "get", item, "--fields", field, "--reveal"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"1Password lookup failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


class Switch:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))

    def _req(self, path, data=None, timeout=20):
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(
            f"http://{HOST}{path}", data=body,
            headers={"User-Agent": "Mozilla/5.0", "Referer": f"http://{HOST}/"})
        return self.op.open(req, timeout=timeout).read().decode("utf-8", "replace")

    def login(self):
        user = op_get(OP_ITEM, "username")
        pw = op_get(OP_ITEM, "password")
        self._req("/logon.cgi", {"username": user, "password": pw, "logon": "Login"})
        del pw
        return any(c.name == "H_P_SSID" for c in self.cj)

    def page(self, path):
        return self._req(path)


def inline_js(html):
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    return m.group(1) if m else ""


def parse(html):
    """Return (scalars, num_arrays, str_arrays) from the page's inline JS."""
    js = inline_js(html)
    scalars, nums, strs = {}, {}, {}

    # var NAME = { key:[...] | key:"..." | key:N };
    for om in re.finditer(r"var\s+(\w+)\s*=\s*\{(.*?)\}\s*;", js, re.S):
        body = om.group(2)
        for km in re.finditer(r"(\w+)\s*:\s*\[(.*?)\]", body, re.S):
            k, inner = km.group(1), km.group(2)
            quoted = re.findall(r'"([^"]*)"', inner)
            if quoted:
                strs[k] = quoted
            else:
                nums[k] = [int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|-?\d+", inner)]
        for km in re.finditer(r"(\w+)\s*:\s*(-?\d+)\s*(?:,|\})", body):
            scalars[km.group(1)] = int(km.group(2))

    # var NAME = new Array(...);
    for am in re.finditer(r"var\s+(\w+)\s*=\s*new\s+Array\((.*?)\)\s*;", js, re.S):
        k, inner = am.group(1), am.group(2)
        quoted = re.findall(r'"([^"]*)"', inner)
        if quoted:
            strs[k] = quoted
        else:
            vals = [int(x) for x in re.findall(r"-?\d+", inner)]
            if vals:
                nums[k] = vals

    # var NAME = N;  /  var NAME = [...];
    for sm in re.finditer(r"var\s+(\w+)\s*=\s*(-?\d+)\s*;", js):
        scalars.setdefault(sm.group(1), int(sm.group(2)))
    for lm in re.finditer(r"var\s+(\w+)\s*=\s*\[(.*?)\]\s*;", js, re.S):
        nums.setdefault(lm.group(1),
                        [int(x) for x in re.findall(r"-?\d+", lm.group(2))])
    return scalars, nums, strs


def show(name, path, html):
    print(f"\n===== {name}  ({path}) =====")
    if 'name="password"' in html:
        print("   ** session rejected (login page returned) **")
        return
    scalars, nums, strs = parse(html)
    nports = scalars.get("portNumber") or scalars.get("max_port_num") or 5

    for k, vals in strs.items():
        if vals:
            label = k.replace("Str", "").replace("_", " ")
            print(f"   {label:22}: {', '.join(vals)}")

    for k, (label, mapping) in SCALARS.items():
        if k in scalars:
            v = scalars[k]
            print(f"   {label:22}: {mapping.get(v, v) if mapping else v}")

    # Port Statistics: pkts is [txGood, txBad, rxGood, rxBad] per port
    if "pkts" in nums and "state" in nums:
        pk = nums["pkts"]
        print(f"\n   {'Port':<6}{'Status':<10}{'Link':<12}{'TxGood':>14}{'TxBad':>8}"
              f"{'RxGood':>14}{'RxBad':>8}")
        for i in range(nports):
            st = STATE.get(nums["state"][i], "?")
            lk = LINK.get(nums.get("link_status", [])[i], "?") \
                if i < len(nums.get("link_status", [])) else "?"
            txg, txb, rxg, rxb = (pk[i*4:i*4+4] + [0, 0, 0, 0])[:4]
            print(f"   {i+1:<6}{st:<10}{lk:<12}{txg:>14}{txb:>8}{rxg:>14}{rxb:>8}")
        return

    for k, vals in nums.items():
        if k in SKIP or not vals:
            continue
        v = vals[:nports] if len(vals) >= nports else vals
        kl = k.lower()
        if k in ("state", "selState", "trunk_info", "enable"):
            v = [STATE.get(x, x) for x in v]
        elif "spd" in kl or "link" in kl:
            v = [LINK.get(x, x) for x in v]
        elif "pri" in kl:
            v = [PRIO.get(x, x) for x in v]
        print(f"   {k:22}: {v}")

    if not scalars and not nums and not strs:
        print("   (no state variables found)")


def main():
    args = sys.argv[1:]
    raw = "--raw" in args
    if raw:
        args.remove("--raw")
    want = [a.lower() for a in args]

    sw = Switch()
    if not sw.login():
        raise SystemExit("login failed (no session cookie) -- someone else logged in?")
    print(f"login OK  ({HOST})")

    for name, path in PAGES:
        if want and not any(w in name.lower() for w in want):
            continue
        try:
            html = sw.page(path)
        except Exception as e:
            print(f"\n===== {name}  ({path}) =====\n   ERROR: {str(e)[:80]}")
            continue
        if raw:
            print(f"\n===== {name} RAW JS =====\n{inline_js(html)[:2000]}")
        else:
            show(name, path, html)


if __name__ == "__main__":
    main()
