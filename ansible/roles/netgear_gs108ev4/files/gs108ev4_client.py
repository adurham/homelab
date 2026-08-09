#!/usr/bin/env python3
"""
NETGEAR GS108Ev4 ("Easy Smart" Plus switch) CGI automation client.

This switch has NO SSH, NO SNMP-write, and NO REST API -- all configuration
happens through HTML <form> POSTs to CGI endpoints, gated by a session
cookie obtained via a homegrown password-hashing scheme in login.js:

    randNum   = <hidden 'rand' field value from GET /login.cgi>
    merged    = interleave(password, randNum)   # char-by-char zip, longer
                                                 # string's leftover tail
                                                 # appended as-is
    submitPwd = MD5(merged)                     # hex digest
    POST /login.cgi  password=<submitPwd>

On success the switch sets a session cookie (typically named `SID` or
similar -- confirm from Set-Cookie on first successful login) that must be
sent with every subsequent request.

IMPORTANT -- this file is a SKELETON. The exact field names for the
IP-configuration and VLAN/QoS CGI endpoints (ip.cgi, vlan.cgi, qos.cgi or
similarly named) have NOT been verified against the live switch, because
we don't have valid credentials yet (its password is on the physical
label, not yet transcribed). Before running any of the `set_*` methods in
anger:

  1. Get the password off the switch's bottom label.
  2. Run `discover_forms()` below against the live switch to dump every
     reachable page's raw HTML/form field names into
     /tmp/gs108ev4_discovery/ for inspection.
  3. Fill in the TODO field-name placeholders in set_static_ip() and
     set_port_qos_priority() to match what discover_forms() reveals.
  4. Test set_static_ip() FIRST and confirm the switch is still reachable
     at its new address before doing anything else -- a bad IP config on
     a switch with no fallback/reset access short of physical button
     press is the single highest-risk action here.

Usage (once verified):
    python3 gs108ev4_client.py --host 192.168.0.239 --password '<label pw>' \
        --set-ip 192.168.86.199 --netmask 255.255.255.0 --gateway 192.168.86.1
"""
import argparse
import hashlib
import re
import sys
import tempfile
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 8


class GS108Ev4Client:
    def __init__(self, host, password, verify_ssl=False, timeout=DEFAULT_TIMEOUT):
        self.base = f"http://{host}"
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl

    @staticmethod
    def _merge(a: str, b: str) -> str:
        """Character-interleave two strings per the switch's login.js `merge()`."""
        out = []
        i = j = 0
        while i < len(a) or j < len(b):
            if i < len(a):
                out.append(a[i])
                i += 1
            if j < len(b):
                out.append(b[j])
                j += 1
        return "".join(out)

    def _get_rand(self):
        resp = self.session.get(f"{self.base}/login.cgi", timeout=self.timeout)
        resp.raise_for_status()
        m = re.search(r"id='rand' value='(\d+)'", resp.text)
        if not m:
            raise RuntimeError(
                "Could not find 'rand' nonce in /login.cgi response -- "
                "page structure may have changed."
            )
        return m.group(1)

    def login(self) -> bool:
        rand = self._get_rand()
        merged = self._merge(self.password, rand)
        pwd_hash = hashlib.md5(merged.encode()).hexdigest()  # noqa: S324 -- required by the switch's own login.js hashing scheme, not used for security
        resp = self.session.post(
            f"{self.base}/login.cgi",
            data={"password": pwd_hash},
            timeout=self.timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
        # Heuristic: failed login re-renders the login page (contains
        # 'Invalid Password' string / login form again); success redirects
        # to the switch's home/status page.
        if "Invalid Password" in resp.text or "id=\"password\"" in resp.text:
            return False
        return True

    def discover_forms(self, out_dir=None):
        """Dump every plausibly-reachable admin page for manual field-name
        inspection. Run this ONCE after a successful login, before writing
        any set_* logic against guessed field names."""
        if out_dir is None:
            out_dir = Path(tempfile.gettempdir()) / "gs108ev4_discovery"  # noqa: S108 -- interactive one-off debug tool, not a shared/predictable-path attack surface
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        candidates = [
            "index.htm", "status.htm", "switch_info.htm",
            "ip_setting.cgi", "ip.cgi", "network.cgi",
            "vlan_type.cgi", "qvlan.cgi", "portVlan.cgi",
            "qos.cgi", "qos_page.cgi", "port_setting.cgi",
            "port_statistics.cgi", "monitoring.cgi",
        ]
        results = {}
        for c in candidates:
            try:
                r = self.session.get(f"{self.base}/{c}", timeout=self.timeout)
                results[c] = r.status_code
                if r.status_code == 200 and len(r.text) > 200:
                    (Path(out_dir) / c.replace("/", "_")).write_text(r.text)
            except requests.RequestException as e:
                results[c] = f"ERROR: {e}"
        return results

    def set_static_ip(self, ip, netmask, gateway):
        """TODO: verify field names via discover_forms() before use.
        Placeholder based on common Netgear Easy-Smart conventions seen in
        community reverse-engineering writeups (field names vary by fw
        version -- DO NOT trust this without confirming against the live
        page source first)."""
        raise NotImplementedError(
            "Field names not yet verified against live switch. "
            "Run discover_forms() first, inspect the IP-config page's "
            "<form> field names, then implement this method."
        )

    def set_port_qos_priority(self, port_priorities: dict):
        """port_priorities: {port_number(1-8): priority_level(0-3)}
        TODO: same caveat as set_static_ip -- verify field names first."""
        raise NotImplementedError(
            "Field names not yet verified against live switch. "
            "Run discover_forms() first."
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--discover", action="store_true",
                     help="Log in and dump reachable admin pages for field-name inspection")
    ap.add_argument("--set-ip")
    ap.add_argument("--netmask", default="255.255.255.0")
    ap.add_argument("--gateway")
    args = ap.parse_args()

    client = GS108Ev4Client(args.host, args.password)
    if not client.login():
        print("LOGIN FAILED -- check password (from the switch's bottom label)", file=sys.stderr)
        sys.exit(1)
    print("Login OK.")

    if args.discover:
        results = client.discover_forms()
        for path, status in results.items():
            print(f"  {path}: {status}")
        print("Full page bodies saved to /tmp/gs108ev4_discovery/ for inspection.")

    if args.set_ip:
        client.set_static_ip(args.set_ip, args.netmask, args.gateway)


if __name__ == "__main__":
    main()
