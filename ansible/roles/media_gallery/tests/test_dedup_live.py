#!/usr/bin/env python3
"""Plain-python tests for dedup_live.py's ingest-time duplicate logic.

Run with:  python3 tests/test_dedup_live.py   (from the role dir)
Requires Python 3.10+ (dedup_scan's popcount uses int.bit_count / the banding
assert). No pytest dependency — plain asserts + main() that prints PASS/FAIL and
exits non-zero on failure.

Tests the PURE/decision logic only. Nothing here touches rclone/network: the
hash-cache path is monkeypatched and save_hidden is called with a temp-path
override (which skips the Drive mirror entirely — see save_hidden's docstring).
"""
import sys
import tempfile
import traceback
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"
sys.path.insert(0, str(FILES_DIR))

import dedup_live  # noqa: E402


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


def _make_image(path, seed):
    """Small grayscale-ish PNG with deterministic pseudo-noise so two calls with
    the same seed produce identical pixels and different seeds differ."""
    from PIL import Image, ImageDraw
    import random
    rng = random.Random(seed)  # noqa: S311 — test-only image noise, not security
    im = Image.new("RGB", (48, 64))
    d = ImageDraw.Draw(im)
    for x in range(0, 48, 2):
        for y in range(0, 64, 2):
            c = rng.randint(0, 255)
            d.rectangle([x, y, x + 1, y + 1], fill=(c, c, c))
    im.save(path)


def test_dhash_determinism():
    with tempfile.TemporaryDirectory() as td:
        a1 = Path(td) / "a1.png"
        a2 = Path(td) / "a2.png"
        b = Path(td) / "b.png"
        _make_image(a1, 1)
        _make_image(a2, 1)  # identical pixels to a1
        _make_image(b, 2)   # visually different
        ha1 = dedup_live.dhash(a1)
        ha2 = dedup_live.dhash(a2)
        hb = dedup_live.dhash(b)
        if ha1 != ha2:
            raise AssertionError(f"same image hashed differently: {ha1:x} vs {ha2:x}")
        if ha1 == hb:
            raise AssertionError("visually different images produced the same hash")


def test_find_newest_match():
    exact = 0xABCDEF0123456789
    far = exact ^ 0b1111111      # distance 7 (> HAMMING=6)
    cache = {
        "old": exact ^ 0b1,           # distance 1, older date
        "newer": exact ^ 0b10,        # distance 2, newer date
        "far": far,                   # distance 7 — must NEVER be a match for `exact`
    }
    dates = {"old": "2026-01-01T00:00:00", "newer": "2026-06-01T00:00:00",
             "far": "2026-12-01T00:00:00"}
    # among the two within-threshold candidates, pick the newer one (far is out)
    m = dedup_live.find_newest_match(exact, cache, dates)
    if m != "newer":
        raise AssertionError(f"expected to pick newer within-threshold candidate, got {m!r}")
    # distance-7 item must not match a distance-0 query... but a query that IS the
    # far hash matches far exactly.
    m_far = dedup_live.find_newest_match(far, cache, dates)
    if m_far != "far":
        raise AssertionError(f"expected far to match itself, got {m_far!r}")
    # no match anywhere within threshold (both candidates are distance ~32)
    none = {"a": 0, "b": (1 << 64) - 1}
    m_none = dedup_live.find_newest_match(0x5555555555555555, none, dates)
    if m_none is not None:
        raise AssertionError(f"expected no match, got {m_none!r}")


def test_decide_hide():
    d = dedup_live.decide_hide
    # new item strictly newer -> hide the matched (older) one
    r = d("new", "2026-07-01", "old", "2026-01-01", set())
    if r != "hide_matched":
        raise AssertionError(f"newer-new should hide matched, got {r!r}")
    # equal/older new -> hide the new one
    r = d("new", "2026-01-01", "old", "2026-07-01", set())
    if r != "hide_new":
        raise AssertionError(f"older-new should hide new, got {r!r}")
    r = d("new", "2026-01-01", "old", "2026-01-01", set())
    if r != "hide_new":
        raise AssertionError(f"tie date should hide new, got {r!r}")
    # a user-KEPT matched stem always wins (hide the new one), even if new is newer
    r = d("new", "2026-07-01", "old", "2026-01-01", {"old"})
    if r != "hide_new":
        raise AssertionError(f"kept matched must not be hidden, got {r!r}")


def test_hidden_ledger_semantics():
    """load_hidden/save_hidden round-trip + the hidden∩keep=∅ invariant survives
    the ingest decision logic, using a temp-path override (no Drive mirror)."""
    from dedup_live import decide_hide, load_hidden, save_hidden
    with tempfile.TemporaryDirectory() as td:
        hp = Path(td) / "hidden.json"
        # empty file -> empty sets
        h0 = load_hidden(hp)
        if h0 != {"hidden": set(), "keep": set()}:
            raise AssertionError(f"missing file should give empty sets, got {h0!r}")
        # simulate a check_ingest_batch decision: matched is user-KEPT -> hide new
        h = load_hidden(hp)
        h["keep"].add("matched")
        act = decide_hide("newstem", "2026-07-01", "matched", "2026-01-01", h["keep"])
        if act == "hide_matched":
            h["hidden"].add("matched")
            h["keep"].discard("matched")
        else:
            h["hidden"].add("newstem")
            h["keep"].discard("newstem")
        save_hidden(h, hp)
        h2 = load_hidden(hp)
        if h2["hidden"] != {"newstem"}:
            raise AssertionError(f"expected newstem hidden, got {h2['hidden']!r}")
        if h2["keep"] != {"matched"}:
            raise AssertionError(f"keep must survive, got {h2['keep']!r}")
        if h2["hidden"] & h2["keep"]:
            raise AssertionError(f"hidden∩keep not empty: {h2['hidden'] & h2['keep']}")
        # re-ingest same newstem now that matched is kept: always hide the new stem
        act2 = decide_hide("newstem", "2026-08-01", "matched", "2026-01-01", h2["keep"])
        if act2 != "hide_new":
            raise AssertionError(f"kept-matched must force hide_new, got {act2!r}")
        # write corrupt file -> empty sets
        hp.write_text("{ not json")
        h3 = load_hidden(hp)
        if h3 != {"hidden": set(), "keep": set()}:
            raise AssertionError(f"corrupt file should give empty sets, got {h3!r}")


def test_check_ingest_batch_decision_via_helper():
    """End-to-end of check_ingest_batch's locking/ledger update using the real
    check_ingest_batch with a temp datemap + monkeypatched hash cache, and a
    temp HIDDEN_FILE — verifies matched-in-keep -> hide_new flows through."""
    from dedup_live import (
        DATEMAP_CACHE, HIDDEN_FILE, check_ingest_batch, dhash, load_hidden,
    )
    import json
    import tempfile as _tf

    with _tf.TemporaryDirectory() as td:
        td = Path(td)
        # two identical images => identical hashes (distance 0)
        im1, im2 = td / "im1.png", td / "im2.png"
        _make_image(im1, 7)
        _make_image(im2, 7)

        # monkeypatch the disk cache + datemap + hidden file into the module so
        # check_ingest_batch writes to temp paths.
        datemap_file = td / "datemap.json"

        # simplest: replace save_hash_cache / load_hash_cache with closures
        real_cache = {"existing": dhash(im1)}
        from dedup_live import load_hash_cache, save_hash_cache
        orig_load = load_hash_cache
        orig_save = save_hash_cache
        dedup_live.load_hash_cache = lambda: dict(real_cache)
        dedup_live.save_hash_cache = lambda c: real_cache.update(c)
        # point hidden file + datemap at temp paths
        orig_hidden = HIDDEN_FILE
        dedup_live.HIDDEN_FILE = td / "hidden.json"
        orig_datemap = DATEMAP_CACHE
        dedup_live.DATEMAP_CACHE = datemap_file
        # redirect the fcntl lock files to temp paths so the run needs no /var/lock
        orig_clock = dedup_live.CACHE_LOCK
        orig_hlock = dedup_live.HIDDEN_LOCK
        dedup_live.CACHE_LOCK = td / "cache.lock"
        dedup_live.HIDDEN_LOCK = td / "hidden.lock"
        # never actually run rclone from a test (no network): stub it. save_hidden
        # calls the module-level rclone() to mirror; a working (or absent) rclone
        # binary must not be required for the test to pass. Left installed for the
        # whole process (deliberately NOT restored) because the daemon mirror
        # thread check_ingest_batch spawns runs after save_hidden returns, so the
        # no-op stub guarantees it can never hit the network.
        dedup_live.rclone = lambda *a: type("R", (), {"returncode": 0, "stderr": ""})()
        try:
            datemap_file.write_text(json.dumps({
                "existing": {"date": "2026-01-01T00:00:00", "out": False, "src": "source"},
            }))
            # existing is NOT kept, new is older -> hide the NEW stem
            check_ingest_batch(
                [("newstem", str(im2), False)],
                {"newstem": "2025-12-01T00:00:00"},
            )
            h = load_hidden(td / "hidden.json")
            if "newstem" not in h["hidden"] or "existing" in h["hidden"]:
                raise AssertionError(
                    f"expected newstem hidden (older), got hidden={h['hidden']!r}")
            if h["hidden"] & h["keep"]:
                raise AssertionError("invariant broken: hidden ∩ keep non-empty")

            # now mark existing as KEPT; a newer newstem must then be hidden
            # (existing stays kept -> not hidden), i.e. hide_new
            from dedup_live import save_hidden
            h = load_hidden(td / "hidden.json")
            h["keep"].add("existing")
            save_hidden(h, td / "hidden.json")
            check_ingest_batch(
                [("newstem2", str(im2), False)],
                {"newstem2": "2026-06-01T00:00:00"},
            )
            h2 = load_hidden(td / "hidden.json")
            if "existing" in h2["hidden"]:
                raise AssertionError("user-KEPT matched stem must never be hidden")
            if "newstem2" not in h2["hidden"]:
                raise AssertionError("expected newstem2 hidden (matched is kept)")
            if h2["hidden"] & h2["keep"]:
                raise AssertionError("invariant broken after keep case")

            # videos are skipped entirely
            h3 = load_hidden(td / "hidden.json")
            before = set(h3["hidden"])
            check_ingest_batch([("vid1", str(im2), True)], {"vid1": "2026-01-01"})
            h4 = load_hidden(td / "hidden.json")
            if set(h4["hidden"]) != before:
                raise AssertionError("video must not be processed by dedup")
        finally:
            dedup_live.load_hash_cache = orig_load
            dedup_live.save_hash_cache = orig_save
            dedup_live.HIDDEN_FILE = orig_hidden
            dedup_live.DATEMAP_CACHE = orig_datemap
            dedup_live.CACHE_LOCK = orig_clock
            dedup_live.HIDDEN_LOCK = orig_hlock


def test_check_ingest_batch_self_match():
    """Re-ingesting a stem whose hash is ALREADY in the cache is a self-match
    (distance 0) and must NEVER hide anything. The re-pushed (idempotent) item's
    hash is refreshed but the hidden ledger stays untouched — a visible item must
    not hide itself. Regression for the live bug where a Telegram re-push with
    the same stem_override staged the SAME stem and check_ingest_batch hid it."""
    from dedup_live import (
        DATEMAP_CACHE, HIDDEN_FILE, check_ingest_batch, dhash, load_hidden,
    )
    import json
    import tempfile as _tf

    with _tf.TemporaryDirectory() as td:
        td = Path(td)
        im = td / "im.png"
        _make_image(im, 9)  # the stem's own hash, already indexed

        real_cache = {"tg_42_99": dhash(im)}
        from dedup_live import load_hash_cache, save_hash_cache
        orig_load = load_hash_cache
        orig_save = save_hash_cache
        dedup_live.load_hash_cache = lambda: dict(real_cache)
        dedup_live.save_hash_cache = lambda c: real_cache.update(c)
        orig_hidden = HIDDEN_FILE
        dedup_live.HIDDEN_FILE = td / "hidden.json"
        orig_datemap = DATEMAP_CACHE
        datemap_file = td / "datemap.json"
        dedup_live.DATEMAP_CACHE = datemap_file
        orig_clock = dedup_live.CACHE_LOCK
        orig_hlock = dedup_live.HIDDEN_LOCK
        dedup_live.CACHE_LOCK = td / "cache.lock"
        dedup_live.HIDDEN_LOCK = td / "hidden.lock"
        dedup_live.rclone = lambda *a: type("R", (), {"returncode": 0, "stderr": ""})()
        try:
            datemap_file.write_text(json.dumps({
                "tg_42_99": {"date": "2026-01-01T00:00:00", "out": False, "src": "source"},
            }))
            # re-ingest the SAME stem whose hash is already in the cache
            check_ingest_batch(
                [("tg_42_99", str(im), False)],
                {"tg_42_99": "2026-01-01T00:00:00"},
            )
            h = load_hidden(td / "hidden.json")
            if "tg_42_99" in h["hidden"]:
                raise AssertionError(
                    f"self-match re-ingest must not hide its own stem, got hidden={h['hidden']!r}")
            if set(h["hidden"]):
                raise AssertionError(f"re-ingest hid something: hidden={h['hidden']!r}")
            if h["hidden"] & h["keep"]:
                raise AssertionError("invariant broken: hidden ∩ keep non-empty")
            # the hash is still (re-)refreshed into the cache
            if real_cache.get("tg_42_99") != dhash(im):
                raise AssertionError("re-ingested stem hash not refreshed in cache")
        finally:
            dedup_live.load_hash_cache = orig_load
            dedup_live.save_hash_cache = orig_save
            dedup_live.HIDDEN_FILE = orig_hidden
            dedup_live.DATEMAP_CACHE = orig_datemap
            dedup_live.CACHE_LOCK = orig_clock
            dedup_live.HIDDEN_LOCK = orig_hlock


def main():
    print("test_dedup_live: running")
    check("dhash determinism + differentiation", test_dhash_determinism)
    check("find_newest_match (thresholds + newest-tie)", test_find_newest_match)
    check("decide_hide pure decision", test_decide_hide)
    check("hidden ledger semantics + invariant", test_hidden_ledger_semantics)
    check("check_ingest_batch end-to-end (keep + video skip)", test_check_ingest_batch_decision_via_helper)
    check("check_ingest_batch self-match (re-ingest never hides)", test_check_ingest_batch_self_match)
    print(f"test_dedup_live: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
