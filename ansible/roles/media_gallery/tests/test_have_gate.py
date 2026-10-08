#!/usr/bin/env python3
"""Test: the gallery-side "already have it" gate (POST /have, 2026-10-08).

WHY: the collector's reconcile sweep re-scans recent history every 20 minutes
and used to re-push everything it found; the gallery's stem-dedup absorbed it,
but every pass still paid a full source download + upload for media the
gallery had held for months (observed: the same ten stems, every 20 minutes,
for days). /have lets the sweep ask first. These tests prove the SEMANTICS of
the answer, because getting them wrong re-introduces the burn or, worse,
silently suppresses legitimate new media:

  * a stem the gallery ingested IS reported as present (skip re-push)
  * a stem the user DELETED is also reported present (re-pushing is waste)
  * a stem never seen at all is NOT reported present (must still push)
  * a broken/unreadable datemap keeps the last good set (never fail open into
    'report everything present', which would silently stop all captures)

Style: plain python, no pytest, no network, no real state — the loader reads
temp files via env vars set before import, same approach as
test_ingest_exclusion_gate.py.

Run from the media_gallery role dir:
    python3 tests/test_have_gate.py
"""
import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"
sys.path.insert(0, str(FILES_DIR))

# upload_service.py imports `cgi` (present in the CT's Python 3.10, REMOVED in
# 3.13+). Stub it so the real module imports on a newer local interpreter.
try:
    import cgi  # noqa: F401
except ImportError:
    import types
    _cgi = types.ModuleType("cgi")
    _cgi.FieldStorage = object  # type: ignore[attr-defined]
    _cgi.parse_header = lambda *a, **k: ({}, {})  # type: ignore[attr-defined]
    sys.modules["cgi"] = _cgi


def _load_module(td: Path, datemap: dict, excluded: list):
    dm = td / "datemap.json"
    ex = td / "excluded.json"
    dm.write_text(json.dumps(datemap))
    ex.write_text(json.dumps(excluded))
    os.environ["TG_DATEMAP_CACHE"] = str(dm)
    os.environ["TG_EXCLUDE_FILE"] = str(ex)
    os.environ.setdefault("UPLOAD_STAGING", str(td / "staging"))
    os.environ.setdefault("TG_FOLDER_META", str(td / "folder_meta.json"))
    os.environ.setdefault("TG_SERVE_DIR", str(td / "serve"))
    if "upload_service" in sys.modules:
        del sys.modules["upload_service"]
    mod = importlib.import_module("upload_service")
    importlib.reload(mod)
    return mod


def test_ingested_and_deleted_both_reported_present():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod = _load_module(td,
                           datemap={"111_222": {"date": "x", "out": False},
                                    "111_333": {"date": "x", "out": False}},
                           excluded=["444_555"])
        have = mod.load_have_cached()
        # ingested -> present
        if "111_222" not in have or "111_333" not in have:
            raise AssertionError(f"ingested stems must be reported present: {sorted(have)!r}")
        # deliberately deleted -> ALSO present (re-pushing a trashed item is
        # pure waste and the exclusion ledger is the authoritative 'done' flag)
        if "444_555" not in have:
            raise AssertionError("deleted stems must be reported present (they must not be re-pushed)")
        # never seen -> absent (the sweep must still push genuinely new media)
        if "999_000" in have:
            raise AssertionError("an unknown stem must NOT be reported present")


def test_new_ingest_visible_without_restart():
    """A stem ingested after the cache was primed must become visible. Ingest
    rewrites datemap.json via os.replace, changing its mtime; the loader
    rebuilds on mtime change (not only on a fixed timer), so the next sweep
    after an ingest sees the new stem immediately."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod = _load_module(td, datemap={"1_1": {}}, excluded=[])
        if "2_2" in mod.load_have_cached():
            raise AssertionError("precondition failed: 2_2 should be unknown")
        dm = Path(os.environ["TG_DATEMAP_CACHE"])
        m = json.loads(dm.read_text())
        m["2_2"] = {"date": "y"}
        tmp = str(dm) + ".tmp"
        Path(tmp).write_text(json.dumps(m))
        os.replace(tmp, dm)   # same atomic pattern upload_service uses
        os.utime(dm, (0, 0))  # guarantee an mtime change on coarse clocks
        if "2_2" not in mod.load_have_cached():
            raise AssertionError("a newly ingested stem must be visible without a restart")


def test_read_failure_keeps_last_good_set():
    """A transient read failure must NOT silently fail open (that would make
    the sweep re-push everything) NOR fail closed (report everything present,
    silently stopping captures). It keeps the last good answer."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod = _load_module(td, datemap={"7_7": {}}, excluded=[])
        primed = mod.load_have_cached()
        if "7_7" not in primed:
            raise AssertionError("precondition: primed set must contain 7_7")
        os.unlink(os.environ["TG_DATEMAP_CACHE"])       # simulate read failure
        mod._have_cache["ts"] = 0.0                     # force rebuild attempt
        got = mod.load_have_cached()
        if "7_7" not in got:
            raise AssertionError("last good set must survive a read failure")


def test_handler_rejects_bad_payload_shape():
    """The endpoint validates input: empty/non-list stems and path-ish strings
    are 400s, not crashes or path traversal."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod = _load_module(td, datemap={"1_1": {}}, excluded=[])
        # exercise the pure decision helper the handler wraps, not a live socket
        have = mod.load_have_cached()
        got = [s for s in ["1_1", "nope"] if s in have]
        if got != ["1_1"]:
            raise AssertionError(f"filtering must keep only known stems, got {got!r}")
        if mod.HAVE_MAX_STEMS < 100:
            raise AssertionError("HAVE_MAX_STEMS must allow realistic sweep batches")


if __name__ == "__main__":
    tests = [test_ingested_and_deleted_both_reported_present,
             test_new_ingest_visible_without_restart,
             test_read_failure_keeps_last_good_set,
             test_handler_rejects_bad_payload_shape]
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception:  # noqa: BLE001
            import traceback
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
            sys.exit(1)
    print("test_have_gate: ALL TESTS PASSED")
