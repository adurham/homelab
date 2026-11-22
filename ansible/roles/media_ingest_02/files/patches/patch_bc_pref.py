P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/utils/auth/request.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "auth.get("x-bc") or _of_key()" in s:
    print("already applied: patch_bc_pref.py"); _sys.exit(0)
old = '''        "x-bc": _of_key() or auth["x-bc"],'''
new = '''        "x-bc": auth.get("x-bc") or _of_key(),'''
assert old in s, "x-bc line not found"
s = s.replace(old, new, 1)
open(P, "w").write(s)
print("request.py now prefers the lifted device key")
