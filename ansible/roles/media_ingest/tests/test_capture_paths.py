"""Failure-path tests for the live collector and the sweep's parked drain.

Runs on an ingest guest as the service user, against the real gpg park key but
with every gallery call stubbed -- nothing here can reach the gallery or the
source. All payloads are random bytes carrying a marker.

    sudo -u mediaingest env $(grep -v '^#' /opt/media-ingest/collector.env | xargs -d '\n') \
        GNUPGHOME=/var/lib/media-ingest/gnupg MI_CODE=/opt/media-ingest \
        /opt/media-ingest/venv/bin/python test_capture_paths.py

Each case states the failure it reproduces. Exit status is the number of
failed cases.
"""
import asyncio
import datetime as dt
import errno
import os
import json
import shutil
import sys
import tempfile
from pathlib import Path

CODE = os.environ.get("MI_CODE", os.path.join(os.path.dirname(__file__), "..", "files"))
BASE = Path(os.environ.get("MI_TEST_BASE", "/var/lib/media-ingest"))
REAL_STAGING = Path(os.environ.get("TG_STAGING", str(BASE / "staging")))

work = Path(tempfile.mkdtemp(prefix="mi-test-", dir=str(BASE)))
staging = Path(tempfile.mkdtemp(prefix="t-", dir=str(REAL_STAGING)))  # stays in RAM
failed = work / "failed"
os.environ.update({
    "TG_STAGING": str(staging),
    "TG_FAILED_DIR": str(failed),
    "TG_METRICS_DIR": str(work / "metrics"),
    "TG_LOG_FILE": str(work / "collector.log"),
    "TG_RECONCILE_LOG": str(work / "reconcile.log"),
})
sys.path.insert(0, CODE)

import collector  # noqa: E402
import reconcile  # noqa: E402
import store_client  # noqa: E402
from telethon.tl.types import MessageMediaPhoto  # noqa: E402

MARK = b"PLAINTEXT-MARKER-" + os.urandom(8).hex().encode()
PAYLOAD = b"\xff\xd8\xff\xe0" + MARK + os.urandom(200_000) + b"\xff\xd9"

pushes = []
push_ok = {"v": True}
gallery_has = set()


def fake_push(folder, path, stem, date_iso, is_out):
    if not push_ok["v"]:
        raise RuntimeError("stub: gallery unavailable")
    pushes.append((stem, Path(path).read_bytes()))
    gallery_has.add(stem)
    return {}


store_client.push_media = fake_push
store_client.get_excluded = lambda: set()
store_client.have_stems = lambda stems: {s for s in stems if s in gallery_has}
order = []


def fake_folder_for(cid, name):
    order.append("gallery-lookup")
    return "zz-test"


collector.folder_for = fake_folder_for

stage_mode = {"v": "ok"}


def fake_open_staged(path):
    if stage_mode["v"] == "enospc":
        raise OSError(errno.ENOSPC, "No space left on device")
    return open(path, "wb")


collector._open_staged = fake_open_staged
fetches = {"n": 0}


class FakeClient:
    def __init__(self, source_has_bytes=True):
        self.source_has_bytes = source_has_bytes

    def iter_download(self, media):
        order.append("download")
        fetches["n"] += 1

        async def gen():
            if self.source_has_bytes:
                for i in range(0, len(PAYLOAD), 65536):
                    yield PAYLOAD[i:i + 65536]
        return gen()


class FakeMsg:
    out = False
    sticker = None
    video = video_note = gif = document = None
    photo = object()

    def __init__(self, mid, ephemeral, staging_mode):
        self.id = mid
        self.date = dt.datetime.now(dt.timezone.utc)
        self.media = MessageMediaPhoto(ttl_seconds=10 if ephemeral else None)
        self._mode = staging_mode

    async def download_media(self, file):
        order.append("download")
        if self._mode == "enospc":
            open(file + ".jpg", "wb").close()  # what a full tmpfs leaves behind
            raise OSError(errno.ENOSPC, "No space left on device")
        if self._mode == "empty":
            return None
        path = file + ".jpg"
        Path(path).write_bytes(PAYLOAD)
        return path


class FakeEvent:
    is_private = True
    chat_id = 999990

    def __init__(self, msg, client):
        self.message = msg
        self.client = client

    async def get_chat(self):
        class C:
            title = None
            first_name = "zz"
        return C()


def _own(directory, stem):
    out = []
    for p in directory.glob(stem + "*"):
        rest = p.name[len(stem):]
        if rest == "" or rest[0] in ". ":
            out.append(p)
    return out


def staged(stem):
    return _own(staging, stem)


def parked(stem):
    return sorted(p.name for p in _own(failed, stem)) if failed.is_dir() else []


def ciphertext_ok(stem):
    gpgs = [p for p in failed.glob(stem + "*.gpg")]
    return bool(gpgs) and all(MARK not in p.read_bytes() and p.stat().st_size > 1000 for p in gpgs)


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def run(msg, client=None):
    stage_mode["v"] = msg._mode
    asyncio.run(collector.handle(FakeEvent(msg, client or FakeClient())))


def m(name):
    return collector._metrics[name]


# 1. The incident: staging is full when an ephemeral item arrives.
before = m("media_ingest_capture_lost_total")
run(FakeMsg(101, ephemeral=True, staging_mode="enospc"))
s = "999990_101"
check("full staging: ephemeral item is captured as ciphertext", ciphertext_ok(s), parked(s))
check("full staging: sidecar written", (failed / (s + ".json")).exists())
check("full staging: sidecar carries the folder once the gallery answered",
      '"zz-test"' in (failed / (s + ".json")).read_text())
check("full staging: no zero-byte leftover in staging", not staged(s), staged(s))
check("full staging: not counted as lost", m("media_ingest_capture_lost_total") == before)
check("full staging: counted as a failed live capture",
      m("media_ingest_capture_failures_total") >= 1)

# 2. Ephemeral item, push fails: an encrypted copy must already exist.
push_ok["v"] = False
fetches["n"] = 0
run(FakeMsg(102, ephemeral=True, staging_mode="ok"))
s = "999990_102"
check("push fails: ephemeral item was fetched from the source exactly once",
      fetches["n"] == 1, fetches)
check("push fails: ephemeral item parked as ciphertext", ciphertext_ok(s), parked(s))
check("push fails: plaintext held in RAM staging for the sweep", len(staged(s)) == 1, staged(s))

# 3. The sweep's drain pushes that held plaintext once the gallery is back.
push_ok["v"] = True
p_, f_, manual = reconcile.push_parked()
check("drain: held item pushed with original bytes",
      any(st == s and data == PAYLOAD for st, data in pushes), (p_, f_, manual))
check("drain: staging and park both cleared", not staged(s) and not parked(s),
      (staged(s), parked(s)))

# 4. Item 101 has ciphertext only (no plaintext anywhere): needs the off-box key.
p_, f_, manual = reconcile.push_parked()
check("drain: ciphertext-only item is reported, not dropped",
      manual == 1 and ciphertext_ok("999990_101"), (p_, f_, manual))

# 5. Ephemeral item, healthy path: parked first, park removed after the push.
run(FakeMsg(103, ephemeral=True, staging_mode="ok"))
s = "999990_103"
check("healthy: pushed", any(st == s for st, _ in pushes))
check("healthy: nothing left in staging or park", not staged(s) and not parked(s),
      (staged(s), parked(s)))

# 6. Source has no bytes and staging is full: the one case that IS a loss.
before = m("media_ingest_capture_lost_total")
run(FakeMsg(104, ephemeral=True, staging_mode="enospc"), FakeClient(source_has_bytes=False))
check("unobtainable: counted as lost", m("media_ingest_capture_lost_total") == before + 1)
check("unobtainable: no empty ciphertext left behind", not parked("999990_104"),
      parked("999990_104"))

# 7. A parked item the gallery already holds is cleared by the drain.
gallery_has.add("999990_101")
reconcile.push_parked()
check("drain: redundant parked copy cleared", not parked("999990_101"), parked("999990_101"))

# 8. The gallery is never consulted before the bytes are in hand (those calls
#    block for the gateway timeout when it is down -- measured at 2-5 minutes
#    per item, which is how disappearing media was missed).
order.clear()
run(FakeMsg(105, ephemeral=True, staging_mode="ok"))
check("ordering: download happens before any gallery lookup",
      order[:1] == ["download"] and "gallery-lookup" in order, order)

# 9. An item parked before its folder was known is routed by chat id at drain.
(staging / "999990_106.jpg").write_bytes(PAYLOAD)
failed.mkdir(parents=True, exist_ok=True)
(failed / "999990_106.json").write_text(json.dumps(
    {"stem": "999990_106", "folder": None, "date": "", "encrypted": True}))
reconcile.push_parked(dynmap={"999990": "zz-map"})
check("drain: folder-less parked item pushed via the chat-id map",
      any(st == "999990_106" for st, _ in pushes) and not staged("999990_106"))

# 10. Ordinary (re-fetchable) item with staging full: captured as ciphertext.
run(FakeMsg(107, ephemeral=False, staging_mode="enospc"))
check("full staging: ordinary item is captured as ciphertext", ciphertext_ok("999990_107"),
      parked("999990_107"))

# 11. Clearing one item never touches another whose id merely starts the same.
(failed / "999990_1079.jpg.gpg").write_bytes(b"x" * 2000)
(failed / "999990_1079.json").write_text(json.dumps(
    {"stem": "999990_1079", "folder": "zz-test", "date": "", "encrypted": True}))
collector._unpark("999990_107")
check("prefix: clearing an item leaves its longer-id neighbour alone",
      not parked("999990_107") and len(parked("999990_1079")) == 2,
      (parked("999990_107"), parked("999990_1079")))
collector._unpark("999990_1079")

# 12. The sweep keeps its hands off an item the collector holds the lock on.
(staging / "999990_108.jpg").write_bytes(PAYLOAD)
(failed / "999990_108.json").write_text(json.dumps(
    {"stem": "999990_108", "folder": "zz-test", "date": "", "encrypted": True}))
import ingest_metrics  # noqa: E402
lk = ingest_metrics.StemLock(staging, "999990_108")
check("lock: acquired", lk.acquire())
before_n = len(pushes)
reconcile.push_parked()
check("lock: sweep skipped the held item", len(pushes) == before_n and staged("999990_108"))
lk.release()
reconcile.push_parked()
check("lock: sweep pushed it once released",
      any(st == "999990_108" for st, _ in pushes) and not staged("999990_108"))

# 13. A park whose gpg dies must not destroy the earlier good ciphertext.
(staging / "999990_109.jpg").write_bytes(PAYLOAD)
check("atomic: first park ok", collector._park_failed("999990_109", "zz-test", "", keep_plain=True))
good = (failed / "999990_109.jpg.gpg").read_bytes()
real_recipient = collector.PARK_RECIPIENT
collector.PARK_RECIPIENT = "nobody@invalid.invalid"
collector._park_failed("999990_109", "zz-test", "", keep_plain=True)
collector.PARK_RECIPIENT = real_recipient
check("atomic: failed re-park left the good ciphertext intact",
      (failed / "999990_109.jpg.gpg").read_bytes() == good and
      not list(failed.glob("*.part")))

# 14. Metrics file is written and carries no identifiers.
prom = (work / "metrics" / "media_ingest_collector.prom")
body = prom.read_text() if prom.exists() else ""
check("metrics: file written", "media_ingest_capture_failures_total" in body)
check("metrics: no stems in metrics", "999990" not in body)

shutil.rmtree(work, ignore_errors=True)
shutil.rmtree(staging, ignore_errors=True)
bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
sys.exit(len(bad))
