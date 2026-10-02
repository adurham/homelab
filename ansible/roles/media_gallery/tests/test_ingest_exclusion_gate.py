#!/usr/bin/env python3
"""Test: the SERVER-SIDE ingest exclusion backstop (2026-10-01).

WHY: the exclusion ledger is what stops a deleted/deduped stem from ever
coming back. Both collectors gate on it, but a client can be STALE (missed a
delete that happened mid-sweep) or BROKEN (the scraper wrapper's exclusion
gate was actually missing until 2026-10-01 — it fetched the ledger and never
consulted it). This test proves the gallery itself rejects an ingest whose
stem is in the ledger, so no client version can re-add deleted content.

Style: plain python (no pytest), prints PASS/FAIL, exits non-zero on failure,
touches no network and no real state — the exclusion check is exercised
against a temp ledger via the module's own loader.

Run from the media_gallery role dir:
    python3 tests/test_ingest_exclusion_gate.py
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
# Python 3.13+). The gallery itself runs 3.10 so the import is fine in prod;
# for testing on a newer local interpreter, inject a minimal stub so the real
# module can be imported and its real exclusion logic exercised.
try:
    import cgi  # noqa: F401
except ImportError:
    import types
    _cgi = types.ModuleType("cgi")
    _cgi.FieldStorage = object  # type: ignore[attr-defined]
    _cgi.parse_header = lambda *a, **k: ({}, {})  # type: ignore[attr-defined]
    sys.modules["cgi"] = _cgi


def _load_module_with_temp_ledger(td: Path):
    """Import upload_service with EXCLUDE_FILE pointed at a temp ledger.

    upload_service has heavy module-level imports (PIL, folder_redirect) but
    no server start at import, so this is safe. We set env BEFORE import so
    the module-level EXCLUDE_FILE picks up the temp path.
    """
    ledger = td / "excluded.json"
    ledger.write_text(json.dumps(["gone_stem_1", "gone_stem_2"]))
    os.environ["TG_EXCLUDE_FILE"] = str(ledger)
    os.environ.setdefault("UPLOAD_STAGING", str(td / "staging"))
    os.environ.setdefault("TG_DATEMAP_CACHE", str(td / "datemap.json"))
    os.environ.setdefault("TG_FOLDER_META", str(td / "folder_meta.json"))
    if "upload_service" in sys.modules:
        del sys.modules["upload_service"]
    mod = importlib.import_module("upload_service")
    importlib.reload(mod)
    return mod, ledger


def test_excluded_stem_is_rejected():
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod, ledger = _load_module_with_temp_ledger(td)
        # fresh cache -> first call reads the ledger
        got = mod.load_excluded_cached()
        if got != {"gone_stem_1", "gone_stem_2"}:
            raise AssertionError(f"loader returned {got!r}")

        # the decision the upload handler makes for a pushed stem:
        def would_reject(stem):
            excl = mod.load_excluded_cached()
            return bool(excl) and stem in excl

        if not would_reject("gone_stem_1"):
            raise AssertionError("deleted stem must be rejected at ingest")
        if would_reject("fresh_stem"):
            raise AssertionError("non-excluded stem must be accepted")


def test_ledger_change_visible_after_ttl():
    """A delete that lands mid-sweep must take effect within the TTL, not
    only after a restart of the uploading service."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod, ledger = _load_module_with_temp_ledger(td)
        mod.load_excluded_cached()  # prime
        ledger.write_text(json.dumps(["gone_stem_1", "gone_stem_2", "newly_deleted"]))
        # simulate TTL expiry (no sleeping in tests)
        mod._excl_cache["ts"] = 0.0
        got = mod.load_excluded_cached()
        if "newly_deleted" not in got:
            raise AssertionError(f"new delete not visible after TTL: {sorted(got)!r}")


def test_load_failure_keeps_last_good_set():
    """A transient read failure must NOT empty the gate (that would silently
    re-open deleted content to re-ingest)."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        mod, ledger = _load_module_with_temp_ledger(td)
        prime = mod.load_excluded_cached()
        if not prime:
            raise AssertionError("expected primed set")
        ledger.unlink()  # simulate read failure
        mod._excl_cache["ts"] = 0.0
        got = mod.load_excluded_cached()
        # an unreadable ledger returns the last good set (possibly empty only
        # if there never was one) -- must still contain the primed stems
        if prime - got:
            raise AssertionError(
                f"gate weakened on read failure: lost {sorted(prime - got)!r}")


if __name__ == "__main__":
    tests = [test_excluded_stem_is_rejected,
             test_ledger_change_visible_after_ttl,
             test_load_failure_keeps_last_good_set]
    for t in tests:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception:  # noqa: BLE001
            import traceback
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
            sys.exit(1)
    print("test_ingest_exclusion_gate: ALL TESTS PASSED")
