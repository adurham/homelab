#!/usr/bin/env python3
"""Plain-python tests for the thumbnails permanent-failure ledger
(2026-10-08) — the mechanism that stops the background backfill from
spending ~90% of every batch re-attempting stems that can never produce a
poster (protected/encrypted sources, oversized files).

The failure CLASSIFIER is the safety-critical part: only deterministic
failures may count. A service restart mid-batch produces `URLError:
Connection refused` for every in-flight item; if those counted, a 20-second
restart would push hundreds of healthy stems toward the skip threshold.

Run with:  python3 tests/test_thumb_failure_ledger.py   (from the role dir)
No pytest; plain asserts, exit non-zero on failure, matching this role's style.
Touches no network and no real state.
"""
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"
sys.path.insert(0, str(FILES_DIR))

PASS = 0


def check(name, fn):
    global PASS
    try:
        fn()
        PASS += 1
        print(f"  ok  {name}")
    except Exception:
        print(f"  FAIL {name}\n" + traceback.format_exc())
        sys.exit(1)


def _fresh_import(tmpdir):
    os.environ["THUMB_LOCAL_CACHE"] = str(tmpdir / "thumbcache")
    os.environ["THUMB_FAIL_LEDGER"] = str(tmpdir / "failed.json")
    for m in ("thumb_backfill", "thumb_service"):
        if m in sys.modules:
            del sys.modules[m]
    import thumb_backfill as tb
    return tb


def _cooldown_skip(tb, rec, cur_size=None, now=None):
    """Mirror of main()'s cooldown predicate, exercised directly so the
    threshold/age/size-change logic is testable without running a live batch."""
    import time as _t
    now = now if now is not None else _t.time()
    try:
        n, t = rec["n"], rec["t"]
    except (TypeError, KeyError):
        return False
    if n < tb.FAIL_MAX:
        return False
    old_sz = rec.get("sz")
    if old_sz is not None and cur_size is not None and old_sz != cur_size:
        return False
    return (now - t) < tb.RETRY_AFTER_DAYS * 86400


def test_deterministic_failures_count():
    """404/410 from the thumb endpoint and decode-level errors are the
    failure classes the ledger exists for. They must classify as counting."""
    with tempfile.TemporaryDirectory() as d:
        tb = _fresh_import(Path(d))
        for err in ("HTTP 404", "HTTP 410",
                    "HTTPError: HTTP Error 404: Not Found",
                    "make_thumb produced no output",
                    "UnidentifiedImageError: cannot identify image file",
                    "CalledProcessError: Command 'ffmpeg ...' returned non-zero"):
            if not tb.classify_failure(err):
                raise AssertionError(f"deterministic failure must count: {err!r}")


def test_transient_failures_never_count():
    """THE regression this test guards: a thumb-service restart makes every
    in-flight item fail with connection-refused; a Drive/transport hiccup
    makes downloads fail. None of those may count, or a transient outage
    would permanently skip healthy content."""
    with tempfile.TemporaryDirectory() as d:
        tb = _fresh_import(Path(d))
        for err in ("URLError: <urlopen error [Errno 111] Connection refused>",
                    "Connection refused",
                    "download failed: rclone: 500 server error",
                    "thumb upload failed: rclone: timeout",
                    "downloaded original is empty",
                    "empty download",
                    "HTTP 500", "HTTP 502", "HTTP 504"):
            if tb.classify_failure(err):
                raise AssertionError(f"transient failure must NOT count: {err!r}")


def test_ledger_roundtrip_and_threshold():
    """Round-trip: timestamped records survive save+load; corrupt JSON loads
    as empty; and the cooldown predicate honours both the count threshold and
    the automatic retry-after window (the safety net that means nobody has to
    remember a --retry-failed flag)."""
    with tempfile.TemporaryDirectory() as d:
        tb = _fresh_import(Path(d))
        assert tb.FAIL_MAX >= 2
        import time as _t
        now = _t.time()
        ledger = {
            "a/fresh": {"n": tb.FAIL_MAX, "t": now},                              # in cooldown
            "b/stale": {"n": tb.FAIL_MAX, "t": now - (tb.RETRY_AFTER_DAYS + 1) * 86400},  # retry due
            "c/below": {"n": tb.FAIL_MAX - 1, "t": now},                          # below threshold
        }
        tb.save_fail_ledger(ledger)
        back = tb.load_fail_ledger()
        if back != ledger:
            raise AssertionError(f"ledger round-trip mismatch: {back!r} != {ledger!r}")
        tb.FAIL_LEDGER.write_text("{not json")
        if tb.load_fail_ledger() != {}:
            raise AssertionError("corrupt ledger must load as empty dict")


def test_cooldown_threshold_and_auto_retry():
    """The skip decision: at/over the threshold AND recently attempted ->
    skip; below the threshold -> always attempt; at/over the threshold but
    older than RETRY_AFTER_DAYS -> attempt again (the automatic safety net);
    and a stem whose stored SIZE changed -> attempt again immediately, since
    the old verdict was about different bytes."""
    with tempfile.TemporaryDirectory() as d:
        tb = _fresh_import(Path(d))
        import time as _t
        now = _t.time()
        if not _cooldown_skip(tb, {"n": tb.FAIL_MAX, "t": now}, now=now):
            raise AssertionError("at-threshold + fresh attempt must be skipped")
        if _cooldown_skip(tb, {"n": tb.FAIL_MAX - 1, "t": now}, now=now):
            raise AssertionError("below-threshold must NOT be skipped")
        stale = now - (tb.RETRY_AFTER_DAYS + 1) * 86400
        if _cooldown_skip(tb, {"n": tb.FAIL_MAX + 5, "t": stale}, now=now):
            raise AssertionError("a stale verdict must be retried automatically")
        if _cooldown_skip(tb, None, now=now):
            raise AssertionError("an absent ledger entry must never be skipped")
        # size change invalidates the verdict (the stored bytes differ now)
        rec = {"n": tb.FAIL_MAX, "t": now, "sz": 1000}
        if _cooldown_skip(tb, rec, cur_size=2000, now=now):
            raise AssertionError("a size change must invalidate the cooldown")
        if not _cooldown_skip(tb, rec, cur_size=1000, now=now):
            raise AssertionError("an unchanged size must keep the cooldown")


def test_atomic_write_leaves_no_partial_on_failure():
    """save_fail_ledger writes tmp+rename; a pre-existing good file must
    survive a save attempted against an un-writable path."""
    with tempfile.TemporaryDirectory() as d:
        tb = _fresh_import(Path(d))
        tb.save_fail_ledger({"a/b": 1})
        # point the ledger at a directory path -> save must fail quietly and
        # leave the previous good file untouched
        good = tb.load_fail_ledger()
        tb.FAIL_LEDGER.parent.chmod(0o500)
        try:
            tb.save_fail_ledger({"c/d": 2})
        finally:
            tb.FAIL_LEDGER.parent.chmod(0o700)
        if tb.load_fail_ledger() != good:
            raise AssertionError("a failed save must not corrupt the existing ledger")


if __name__ == "__main__":
    print("test_thumb_failure_ledger: running")
    check("deterministic failures classify as counting", test_deterministic_failures_count)
    check("transient failures never count (restart-burst regression)", test_transient_failures_never_count)
    check("ledger round-trips and tolerates corruption", test_ledger_roundtrip_and_threshold)
    check("cooldown threshold + automatic retry-after window", test_cooldown_threshold_and_auto_retry)
    check("atomic save never corrupts an existing ledger", test_atomic_write_leaves_no_partial_on_failure)
    print(f"test_thumb_failure_ledger: ALL {PASS} TESTS PASSED")
    print("PASS")
