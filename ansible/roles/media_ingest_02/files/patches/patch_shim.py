P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/managers/sessionmanager/sessionmanager.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "class _ShimResponse" in s:
    print("already applied: patch_shim.py"); _sys.exit(0)

RESP = '''

class _ShimResponse:
    """Minimal aiohttp-response stand-in for replies fetched through the CDP shim."""

    def __init__(self, status, headers, body):
        self.status = status
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.ok = status < 400
        self.request = None
        self.content = None
        self.eof = True

    async def read_(self):
        return self._body

    async def text_(self):
        return self._body.decode("utf-8", "replace")

    async def json_(self):
        import json as _json
        return _json.loads(self._body)

'''

anchor = "class SessionSleep:"
assert anchor in s
s = s.replace(anchor, RESP.lstrip("\n") + "\n" + anchor, 1)

OLD = '''    async def _aio_funct(self, method, *args, **kwargs):
        r = await self._session._request(method, *args, **kwargs)'''
NEW = '''    async def _shim_request(self, method, url, headers=None, params=None, json=None, data=None):
        import base64 as _b64
        import json as _json
        import os as _os
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
        })
        shim = _os.environ.get("OF_SHIM_URL", "http://127.0.0.1:9123")
        async with aiohttp.ClientSession() as s:
            async with s.post(shim + "/fetch", data=payload,
                              headers={"content-type": "application/json"},
                              timeout=aiohttp.ClientTimeout(total=180)) as r:
                out = await r.json()
        if out.get("status") == 0:
            raise RuntimeError("shim fetch failed: %s" % out.get("error"))
        raw = _b64.b64decode(out.get("body_b64") or "")
        return _ShimResponse(int(out["status"]), out.get("headers"), raw)

    async def _aio_funct(self, method, *args, **kwargs):
        import os as _os
        _url = kwargs.get("url") or (args[0] if args else None)
        if isinstance(_url, str) and "onlyfans.com/api2/" in _url:
            return await self._shim_request(
                method, _url,
                headers=kwargs.get("headers"), params=kwargs.get("params"),
                json=kwargs.get("json"), data=kwargs.get("data"))
        r = await self._session._request(method, *args, **kwargs)'''
assert OLD in s
s = s.replace(OLD, NEW, 1)

open(P, "w").write(s)
print("sessionmanager patched for CDP shim")
