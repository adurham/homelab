#!/usr/bin/env python3
"""Minimal Shelly RPC client with digest auth (SHA-256).

Shelly Gen2+ devices with a device password ("Restrict login") require HTTP
digest auth using SHA-256, which Python's urllib does not implement. This
helper does the challenge/response itself and prints the raw JSON response.

Usage:
    shelly_rpc.py <url>                 # GET
    shelly_rpc.py <url> '<json body>'   # POST with a JSON body

Password: read from $SHELLY_PW if set, else from secrets.yaml
(shelly_device_password) next to HA's config.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import urllib.error
import urllib.request

SECRETS = "/config/secrets.yaml"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password() -> str:
    pw = os.environ.get("SHELLY_PW")
    if pw:
        return pw
    import yaml  # available inside the HA container

    with open(SECRETS, encoding="utf-8") as handle:
        return yaml.safe_load(handle)["shelly_device_password"]


def request(url: str, body: str | None, auth: str | None = None):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(
        url, data=body.encode() if body is not None else None,
        headers=headers, method="POST" if body is not None else "GET",
    )
    return urllib.request.urlopen(req, timeout=8)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: shelly_rpc.py <url> [json-body]", file=sys.stderr)
        return 2
    url = sys.argv[1]
    body = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        with request(url, body) as resp:
            print(resp.read().decode())
            return 0
    except urllib.error.HTTPError as err:
        if err.code != 401:
            print(f"HTTP {err.code}", file=sys.stderr)
            return 1
        challenge = err.headers.get("WWW-Authenticate", "")
    parts = dict(re.findall(r'(\w+)="?([^",]+)"?', challenge))
    realm, nonce = parts["realm"], parts["nonce"]
    qop = parts.get("qop", "auth")
    cnonce = os.urandom(8).hex()
    nc = "00000001"
    path = "/" + url.split("/", 3)[3] if url.count("/") >= 3 else "/"
    ha1 = sha256(f"admin:{realm}:{password()}")
    ha2 = sha256(f"{'POST' if body is not None else 'GET'}:{path}")
    response = sha256(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    auth = (
        f'Digest username="admin", realm="{realm}", nonce="{nonce}", '
        f'uri="{path}", algorithm=SHA-256, response="{response}", '
        f'qop={qop}, nc={nc}, cnonce="{cnonce}"'
    )
    with request(url, body, auth) as resp:
        print(resp.read().decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
