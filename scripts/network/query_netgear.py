#!/usr/bin/env python3
"""Query the NETGEAR GS108Ev4 (192.168.86.14) config over HTTP.

Auth (reverse-engineered from /login.js):
    POST /login.cgi  password=md5(merge(realPassword, rand))
where `rand` is a hidden field on the login page and merge() interleaves the
two strings character-by-character (p0 r0 p1 r1 ...). Returns a SID cookie.

IMPORTANT: after logging in you MUST fetch /index.cgi once to fully establish
the session. Without it, subsequent page fetches silently return a
"Redirect to Login" stub even though the SID cookie is set.

State lives directly in the rendered HTML:
  - toggles  -> <input id='xxx' type='checkbox' checked>  (checked == enabled)
  - ports    -> <input class="portName|Speed|LinkedSpeed|..." value="...">
Labels are ml### i18n tokens and are ignored; we key off element ids/classes.

Credentials come from 1Password at call time via `op` -- never stored on disk.

Usage:
    python3 query_netgear.py                # everything
    python3 query_netgear.py toggles        # just the on/off settings
    python3 query_netgear.py ports          # just the port table
    python3 query_netgear.py --backup FILE  # save binary config backup (path required)
"""
import hashlib
import http.cookiejar
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import gzip

HOST = "192.168.86.14"
OP_ITEM = "Netgear GS108Ev4"

# page -> {checkbox id: human label}
TOGGLES = {
    "/loopDetection.cgi":   {"loopPrevMod":  "Loop Prevention"},
    "/powerSaving.cgi":     {"powStateModSet": "Power Saving"},
    "/dos.cgi":             {"dosState":    "DoS Prevention"},
    "/switchDiscovery.cgi": {"upnp_status": "Switch Discovery (NSDP/UPnP)"},
    "/leds.cgi":            {"ledState":    "Port LEDs"},
}


def op_get(item, field):
    r = subprocess.run(["op", "item", "get", item, "--fields", field, "--reveal"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"1Password lookup failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def merge(s1, s2):
    out = []
    for i in range(max(len(s1), len(s2))):
        if i < len(s1):
            out.append(s1[i])
        if i < len(s2):
            out.append(s2[i])
    return "".join(out)


class Switch:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))

    def _raw(self, path, data=None, timeout=25):
        body = urllib.parse.urlencode(data).encode() if data else None
        req = urllib.request.Request(
            f"http://{HOST}{path}", data=body,
            headers={"User-Agent": "Mozilla/5.0", "Referer": f"http://{HOST}/"})
        return self.op.open(req, timeout=timeout).read()

    def get(self, path, data=None):
        b = self._raw(path, data)
        if b[:2] == b"\x1f\x8b":
            b = gzip.decompress(b)
        return b.decode("utf-8", "replace")

    def logout(self):
        """Release the session slot.

        CRITICAL: this switch allows only a few concurrent sessions and holds
        each one until it times out (minutes). Abandoning sessions quickly
        yields "The maximum number of sessions has been reached." -- always
        log out, even on error paths.

        No-op when we don't hold a session (the endpoint 404s unauthenticated).
        """
        if not any(c.name == "SID" for c in self.cj):
            return
        errors = []
        for path in ("/logout.cgi", "/login.cgi?cmd=logout"):
            try:
                self.get(path)
                break
            except Exception as e:  # noqa: S112, BLE001 - try next candidate
                errors.append(f"{path}: {str(e)[:40]}")
        else:
            print(f"   (warning: could not log out -- {'; '.join(errors)})",
                  file=sys.stderr)
        self.cj.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.logout()
        return False

    def login(self, attempts=4, wait=20):
        """Log in, retrying on session contention.

        A "maximum number of sessions" response means slots are occupied by
        earlier sessions that were never closed; they expire on their own, so
        back off and retry rather than failing outright.
        """
        import time
        last = ""
        for n in range(1, attempts + 1):
            self.cj.clear()
            page = self.get("/login.cgi")
            m = re.search(r"""id=['"]?rand['"]?[^>]*?value=['"]?([0-9]+)""", page)
            if not m:
                last = "no rand seed on login page"
                time.sleep(wait)
                continue
            pw = op_get(OP_ITEM, "password")
            # md5 is dictated by the switch firmware's login scheme, not a
            # security choice on our part; usedforsecurity=False documents that.
            digest = hashlib.md5(  # noqa: S324
                merge(pw, m.group(1)).encode(), usedforsecurity=False
            ).hexdigest()
            del pw
            resp = self.get("/login.cgi", {"password": digest})
            if any(c.name == "SID" for c in self.cj):
                # REQUIRED: establishes the session; without it pages
                # silently return "Redirect to Login" stubs
                self.get("/index.cgi")
                return True
            if "maximum number of sessions" in resp.lower():
                last = "session slots full (stale sessions still expiring)"
            elif "Invalid Password" in resp:
                print("login failed: invalid password")
                return False
            else:
                last = "no SID cookie"
            if n < attempts:
                print(f"   attempt {n}: {last}; retrying in {wait}s...")
                time.sleep(wait)
        print(f"login failed after {attempts} attempts: {last}")
        return False


def checkbox_state(html, box_id):
    """True/False if the checkbox exists, else None."""
    m = re.search(r"<input[^>]*id=['\"]%s['\"][^>]*>" % re.escape(box_id), html)
    if not m:
        return None
    return "checked" in m.group(0).lower()


def show_toggles(sw):
    print("\n===== Settings =====")
    for path, boxes in TOGGLES.items():
        try:
            html = sw.get(path)
        except Exception as e:
            for label in boxes.values():
                print(f"   {label:30}: ERROR {str(e)[:40]}")
            continue
        if "Redirect to Login" in html:
            for label in boxes.values():
                print(f"   {label:30}: ** session lost **")
            continue
        for box_id, label in boxes.items():
            st = checkbox_state(html, box_id)
            val = "n/a" if st is None else ("Enabled" if st else "Disabled")
            print(f"   {label:30}: {val}")


def show_ports(sw):
    html = sw.get("/dashboard.cgi")
    if "Redirect to Login" in html:
        print("\n===== Ports =====\n   ** session lost **")
        return
    flat = re.sub(r"\s+", " ", html)

    # One <li class="list_item index_li"> per port; each holds the status span
    # and all of that port's hidden inputs.
    chunks = re.split(r'(?=<li class="list_item index_li">)', flat)
    rows = []
    for c in chunks:
        pm = re.search(r'<input type="hidden" class="port" value="(\d+)"', c)
        if not pm:
            continue

        def grab(cls, chunk=c):
            m = re.search(r'class="%s" value="([^"]*)"' % cls, chunk)
            return m.group(1).strip() if m else ""

        def label_after(cls, chunk=c):
            """The visible <span> text that sits just before a hidden input."""
            m = re.search(r'<span>([^<]*)</span>\s*(?:</div>\s*)?'
                          r'<input type="hidden"[^>]*class="%s"' % cls, chunk)
            return m.group(1).strip() if m else ""

        # status classes vary (text-success-1 / -2) by link state
        st = "UP" if re.search(r'text-success-\d">\s*UP', c) else "AVAILABLE"
        link = grab("LinkedSpeed") or "Link Down"
        if link == "No Speed":
            link = "Link Down"
        rows.append({
            "n": pm.group(1),
            "name": grab("portName") or "-",
            "status": st,
            "link": link,
            "in": label_after("ingressRate") or "-",
            "out": label_after("egressRate") or "-",
            "fc": label_after("flowCtr") or "-",
            "prio": label_after("priority") or "-",
        })

    rows.sort(key=lambda r: int(r["n"]))
    print("\n===== Ports =====")
    print(f"   {'#':<3} {'Name':<18} {'Status':<10} {'Link':<12} "
          f"{'In Limit':<10} {'Out Limit':<10} {'FlowCtl':<8} {'Priority':<9}")
    print("   " + "-" * 92)
    for r in rows:
        print(f"   {r['n']:<3} {r['name']:<18} {r['status']:<10} {r['link']:<12} "
              f"{r['in']:<10} {r['out']:<10} {r['fc']:<8} {r['prio']:<9}")


def show_sysinfo(sw):
    html = sw.get("/dashboard.cgi")
    if "Redirect to Login" in html:
        return
    flat = re.sub(r"\s+", " ", html)
    print("\n===== System =====")
    for label, pat in (
        ("Model",      r'id="switch_name"[^>]*>([^<]+)<'),
        ("IP Address", r'id="overall_ip"[^>]*>([^<]+)<'),
    ):
        m = re.search(pat, flat)
        if m and m.group(1).strip():
            print(f"   {label:30}: {m.group(1).strip()}")
    m = re.search(r"(\d+) PORTS", flat) or re.search(r'id="portNum"[^>]*>(\d+)<', flat)
    if m:
        print(f"   {'Ports connected':30}: {m.group(1)}")


def backup(sw, dest):
    data = sw._raw("/confFile.cgi?cmd=backup_conf")
    if data[:2] != b"NG":
        raise SystemExit(f"unexpected backup payload ({len(data)} bytes)")
    with open(dest, "wb") as f:
        f.write(data)
    model = data[4:16].split(b"\x00")[0].decode()
    print(f"saved {len(data)} bytes -> {dest}  (model {model})")


def main():
    args = sys.argv[1:]
    sw = Switch()
    if not sw.login():
        raise SystemExit(1)
    print(f"login OK  ({HOST})")
    try:
        if "--backup" in args:
            i = args.index("--backup")
            if len(args) <= i + 1:
                raise SystemExit("--backup requires an output path")
            dest = args[i + 1]
            backup(sw, dest)
            return

        want = [a.lower() for a in args]
        if not want or any("sys" in w for w in want):
            show_sysinfo(sw)
        if not want or any(w in ("toggles", "settings", "loop", "power", "dos") for w in want):
            show_toggles(sw)
        if not want or any("port" in w for w in want):
            show_ports(sw)
    finally:
        # always free the session slot -- see logout() docstring
        sw.logout()


if __name__ == "__main__":
    main()
