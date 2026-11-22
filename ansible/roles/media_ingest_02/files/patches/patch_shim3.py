P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/managers/sessionmanager/sessionmanager.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "def raise_for_status(self):" in s:
    print("already applied: patch_shim3.py"); _sys.exit(0)
old = '''    async def read_(self):
        return self._body'''
new = '''    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("shim HTTP %d for %s" % (self.status, self.url))

    async def read_(self):
        return self._body'''
assert old in s
s = s.replace(old, new, 1)
open(P, "w").write(s)
print("raise_for_status added")
