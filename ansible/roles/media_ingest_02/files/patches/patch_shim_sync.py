P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/managers/sessionmanager/sessionmanager.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "class _ShimSyncResponse" in s:
    print("already applied: patch_shim_sync.py"); _sys.exit(0)

SYNC_CLASS = '''

class _ShimSyncResponse:
    """Sync (httpx-shaped) response backed by the CDP shim."""

    class _Req:
        headers = {}

    def __init__(self, status, headers, body, url="", method="GET"):
        self.status_code = status
        self.status = status
        self.ok = status < 400
        self.headers = headers or {}
        self._body = body
        self.url = url
        self.request = self._Req()

    def text_(self):
        return self._body.decode("utf-8", "replace")

    def json_(self):
        import json as _json
        return _json.loads(self._body)

    def read_(self):
        return self._body

    def iter_chunked(self, *a, **k):
        yield self._body

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("shim HTTP %d for %s" % (self.status, self.url))

'''

anchor = "class _ShimResponse:"
assert anchor in s
s = s.replace(anchor, SYNC_CLASS.lstrip("\n") + "\n" + anchor, 1)

OLD = '''    def _httpx_funct(self, method, **kwargs):
        t = self._session.request(method.upper(), **kwargs)'''
NEW = '''    def _shim_sync(self, method, url, headers=None, params=None, json=None, data=None):
        import base64 as _b64
        import json as _json
        import os as _os
        import urllib.request as _ur
        from urllib.parse import urlencode
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urlencode(params, doseq=True)
        body = b""
        if json is not None:
            body = _json.dumps(json).encode()
        elif data is not None:
            body = data if isinstance(data, bytes) else _json.dumps(data).encode()
        hdrs = {k: v for k, v in (headers or {}).items() if k.lower() != "cookie"}
        payload = _json.dumps({
            "method": method.upper(), "url": url, "headers": hdrs,
            "body_b64": _b64.b64encode(body).decode() if body else "",
        }).encode()
        shim = _os.environ.get("OF_SHIM_URL", "http://127.0.0.1:9123")
        req = _ur.Request(shim + "/fetch", data=payload,
                          headers={"content-type": "application/json"})
        with _ur.urlopen(req, timeout=180) as r:
            out = _json.loads(r.read())
        if out.get("status") == 0:
            raise RuntimeError("shim fetch failed: %s" % out.get("error"))
        raw = _b64.b64decode(out.get("body_b64") or "")
        return _ShimSyncResponse(int(out["status"]), out.get("headers"), raw,
                                 url=url, method=method.upper())

    def _httpx_funct(self, method, **kwargs):
        import os as _os
        _url = kwargs.get("url")
        if isinstance(_url, str) and "onlyfans.com/api2/" in _url and _os.environ.get("OF_SHIM_URL"):
            return self._shim_sync(method, _url, headers=kwargs.get("headers"),
                                   params=kwargs.get("params"), json=kwargs.get("json"),
                                   data=kwargs.get("data"))
        t = self._session.request(method.upper(), **kwargs)'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

open(P, "w").write(s)
print("sync path routed through the shim")
