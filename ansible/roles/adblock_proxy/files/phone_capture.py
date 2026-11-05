"""Full-traffic capture addon for the lab Android phone.

DELIBERATELY DIFFERENT from ad_block.py: that addon exists to *filter*
Discord/Reddit and calls `data.ignore_connection = True` for every other SNI,
so everything else is relayed as opaque TLS and nothing is readable. This one
has no tls_clienthello hook at all, so mitmproxy terminates TLS for every flow
it sees and we can read requests, responses and bodies.

Deployed only against traffic that arrived from the phone's source address
(iptables REDIRECT scoped to a single -s), so it can never widen the blast
radius of the household ad-blocking path on 8443.

Logs one JSON line per completed flow to /var/log/mitmproxy/phone-capture.log
(body excerpts truncated) and nothing else; the full stream file written by
--save-stream-file is what you replay in mitmweb for anything deeper.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from mitmproxy import ctx, http

LOG_PATH = "/var/log/mitmproxy/phone-capture.log"
MAX_BODY = 4096
# Never write credential material to the capture log in cleartext-excerpt form;
# log the header names only for these.
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
}


def _log(record: dict[str, Any]) -> None:
    record["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:  # never break a flow because logging failed
        ctx.log.warn(f"phone_capture: log write failed: {exc}")


def _headers(headers) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            out[key] = f"<{len(value)} bytes withheld>"
        else:
            out[key] = value
    return out


def _body_excerpt(message) -> Any:
    if message is None or message.raw_content is None:
        return None
    raw = message.raw_content
    ctype = message.headers.get("content-type", "")
    if ctype.startswith(("text/", "application/json", "application/xml",
                         "application/javascript", "application/x-www-form-urlencoded")):
        try:
            return raw[:MAX_BODY].decode("utf-8", "replace")
        except Exception:
            return None
    return {"binary_b64": base64.b64encode(raw[:1024]).decode(), "size": len(raw)}


class PhoneCapture:
    def request(self, flow: http.HTTPFlow) -> None:
        flow.metadata["pc_start"] = time.time()

    def response(self, flow: http.HTTPFlow) -> None:
        started = flow.metadata.get("pc_start")
        record = {
            "event": "flow",
            "method": flow.request.method,
            "scheme": flow.request.scheme,
            "host": flow.request.pretty_host,
            "path": flow.request.path,
            "url": flow.request.pretty_url,
            "status": flow.response.status_code if flow.response else None,
            "elapsed_ms": int((time.time() - started) * 1000) if started else None,
            "client": flow.client_conn.peername[0] if flow.client_conn.peername else None,
            "req_headers": _headers(flow.request.headers),
            "req_body": _body_excerpt(flow.request),
            "resp_headers": _headers(flow.response.headers) if flow.response else None,
            "resp_body": _body_excerpt(flow.response),
        }
        _log(record)

    def tls_failed_client(self, data) -> None:
        _log({"event": "tls_failed_client",
              "client": str(data.context.client),
              "error": str(data.conn.error) if getattr(data, "conn", None) else None,
              "hint": "client does not trust our CA, or the app pins"})

    def error(self, flow: http.HTTPFlow) -> None:
        _log({"event": "error",
              "url": flow.request.pretty_url if flow.request else None,
              "error": str(flow.error)})


addons = [PhoneCapture()]
