import re

P = "/opt/media-ingest-02/venv/lib/python3.12/site-packages/ofscraper/utils/auth/request.py"
s = open(P).read()
import sys as _sys  # ALREADY-APPLIED-GUARD
if "x-of-rev" in s:
    print("already applied: patch_cdn.py"); _sys.exit(0)

HELPERS = '''

# ── live CDN tokens (added locally) ──────────────────────────────────────────
# OF's frontend fetches x-bc from https://cdn2.onlyfans.com/key/ and x-hash from
# https://cdn2.onlyfans.com/hash/?u=<uid>; both are short-lived server-issued
# values. ofscraper used to synthesise x-bc locally, which the API now rejects.
_CDN_CACHE = {"bc": None, "bc_ts": 0.0, "hash": {}, }


def _cdn_get(url, timeout=8):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace").strip()


def _of_key(ttl=60):
    import time as _t
    now = _t.time()
    if _CDN_CACHE["bc"] and now - _CDN_CACHE["bc_ts"] < ttl:
        return _CDN_CACHE["bc"]
    try:
        v = _cdn_get("https://cdn2.onlyfans.com/key/")
        if v:
            _CDN_CACHE["bc"] = v
            _CDN_CACHE["bc_ts"] = now
        return v or None
    except Exception:
        return _CDN_CACHE["bc"] or None


def _of_hash(uid, ttl=60):
    import time as _t
    now = _t.time()
    hit = _CDN_CACHE["hash"].get(str(uid))
    if hit and now - hit[1] < ttl:
        return hit[0]
    try:
        v = _cdn_get("https://cdn2.onlyfans.com/hash/?u=%s" % uid)
        if v:
            _CDN_CACHE["hash"][str(uid)] = (v, now)
        return v or None
    except Exception:
        return hit[0] if hit else None

'''

anchor = "def make_headers():"
assert anchor in s
s = s.replace(anchor, HELPERS.lstrip("\n") + "\n" + anchor, 1)

old_login = '''        "x-bc": auth["x-bc"],
        "x-of-rev": of_env.getattr("X_OF_REV") or "202611201129-df73dce944",'''
new_login = '''        "x-bc": _of_key() or auth["x-bc"],
        "x-of-rev": of_env.getattr("X_OF_REV") or "202611201129-df73dce944",'''
assert old_login in s
s = s.replace(old_login, new_login, 1)

# add x-hash after the headers dict is built in make_login_headers
old_ret = '''    }
    return headers


def add_cookies():'''
new_ret = '''    }
    _h = _of_hash(auth.get("auth_id"))
    if _h:
        headers["x-hash"] = _h
    return headers


def add_cookies():'''
assert old_ret in s
s = s.replace(old_ret, new_ret, 1)

open(P, "w").write(s)
print("patched request.py")
