P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/managers/sessionmanager/sessionmanager.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "url=url, method=method.upper())" in s:
    print("already applied: patch_shim2.py"); _sys.exit(0)

old_init = '''    def __init__(self, status, headers, body):
        self.status = status
        self.status_code = status
        self.headers = headers or {}
        self._body = body'''
new_init = '''    def __init__(self, status, headers, body, url="", method="GET"):
        self.status = status
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.url = url
        self.real_url = url
        self.method = method'''
assert old_init in s
s = s.replace(old_init, new_init, 1)

old_ret = '''        return _ShimResponse(int(out["status"]), out.get("headers"), raw)'''
new_ret = '''        return _ShimResponse(int(out["status"]), out.get("headers"), raw,
                             url=url, method=method.upper())'''
assert old_ret in s
s = s.replace(old_ret, new_ret, 1)

open(P, "w").write(s)
print("shim response carries url/method")
