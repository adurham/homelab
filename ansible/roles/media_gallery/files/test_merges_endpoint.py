"""Local proof for POST/GET /merges (upload_service) without rclone or the guest.

Stubs the removed-in-3.14 `cgi` module, imports the real service, and runs its
real Handler on a port so the routing, validation and file write are exercised
end to end. Run:  python3 test_merges_endpoint.py
"""
import json
import os
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(os.environ.get("HOME", "/tmp"), ".hermes/cache/scratch/galstub/state")
os.makedirs(STATE, exist_ok=True)
os.environ["TG_GROUPS_FILE"] = os.path.join(STATE, "folder_groups.json")
os.environ["TG_FAVS_FILE"] = os.path.join(STATE, "favs.json")
os.environ["UPLOAD_STAGING"] = os.path.join(STATE, "staging")
os.environ["TG_DATEMAP_CACHE"] = os.path.join(STATE, "datemap.json")
os.environ["TG_EXCLUDE_FILE"] = os.path.join(STATE, "excluded.json")
for p in (os.environ["TG_GROUPS_FILE"], os.environ["TG_FAVS_FILE"]):
    if os.path.exists(p):
        os.unlink(p)

# upload_service imports cgi (gone in 3.14); only the POST body helpers use it.
sys.modules.setdefault("cgi", types.ModuleType("cgi"))
sys.path.insert(0, HERE)
import upload_service as svc  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), svc.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"


def get(path):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


fails = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  " + str(extra)) if extra else ""))
    if not cond:
        fails.append(label)


# 1. empty state
st, d = get("/merges")
check("GET /merges empty -> 200 {groups:[]}", st == 200 and d.get("groups") == [], d)

# 2. a real write
g = {"id": "gabc123", "name": "Merged A", "folders": ["folder one", "folder two"], "ts": 1700000000000}
st, d = post("/merges", {"groups": [g]})
check("POST /merges -> 200 ok", st == 200 and d.get("ok") is True, d)
check("file written", os.path.exists(os.environ["TG_GROUPS_FILE"]))
on_disk = json.load(open(os.environ["TG_GROUPS_FILE"]))
check("stored under 'shared'", list(on_disk) == ["shared"], on_disk)
check("group round-trips", on_disk["shared"][0]["folders"] == ["folder one", "folder two"], on_disk)

st, d = get("/merges")
check("GET returns the group", st == 200 and len(d["groups"]) == 1 and d["groups"][0]["name"] == "Merged A", d)

# 3. tombstone survives
st, d = post("/merges", {"groups": [{"id": "gabc123", "name": "Merged A", "folders": [], "ts": 1700000001000, "del": 1}]})
check("POST tombstone -> 200", st == 200, d)
st, d = get("/merges")
check("tombstone readable with del=1", d["groups"][0].get("del") == 1, d)

# 4. validation
bad = [
    ({"groups": "x"}, "groups not a list"),
    ({"nope": []}, "missing groups"),
    ({"groups": [{"id": "../etc", "name": "x", "folders": [], "ts": 1}]}, "traversal id"),
    ({"groups": [{"id": "g1", "name": "", "folders": [], "ts": 1}]}, "empty name"),
    ({"groups": [{"id": "g1", "name": "n", "folders": ["a/b"], "ts": 1}]}, "slash in folder"),
    ({"groups": [{"id": "g1", "name": "n", "folders": ["a"], "ts": "soon"}]}, "bad ts"),
    ({"groups": [{"id": "g1", "name": "n", "folders": [f"f{i}" for i in range(201)], "ts": 1}]}, "too many members"),
]
for body, label in bad:
    st, d = post("/merges", body)
    check("rejects %s -> 400" % label, st == 400, d)

# 5. empty list clears
st, d = post("/merges", {"groups": []})
check("POST [] clears", st == 200 and json.load(open(os.environ["TG_GROUPS_FILE"]))["shared"] == [], d)

# 6. favs still work (regression: shared _fav_user path)
st, d = post("/favs", {"folders": ["one"]})
check("POST /favs still 200", st == 200 and d.get("count") == 1, d)
st, d = get("/favs")
check("GET /favs still 200", st == 200 and d.get("folders") == ["one"], d)

srv.shutdown()
print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
