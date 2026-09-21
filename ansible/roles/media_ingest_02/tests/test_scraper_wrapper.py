#!/usr/bin/env python3
"""Plain-python tests for media_ingest_02/scraper_wrapper.py's staging-push
stability gate (_walk_and_push).

Run with:  python3 tests/test_scraper_wrapper.py   (from the role dir)
No pytest dependency — plain asserts + main() that prints PASS/FAIL and exits
non-zero on failure, matching the media_gallery role's test style.

scraper_wrapper.py reads several required env vars (M02_STAGING, M02_AUTH_FILE,
M02_CONFIG_FILE) and imports store_client (which itself requires
AUTHENTIK_TOKEN_URL / COLLECTOR_CLIENT_ID / COLLECTOR_CLIENT_SECRET) at MODULE
level. We set fake env vars and inject a stub store_client into sys.modules
BEFORE importing, so the real network/auth code never runs — same "isolate the
side-effecting import" approach as test_dedup_live.py's monkeypatching.
"""
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"

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


def _import_module_fresh(staging_dir):
    """(Re)import scraper_wrapper against a fresh STAGING dir, with a stub
    store_client that records every push_media call instead of hitting the
    network. Returns (module, pushed_calls_list)."""
    import os
    os.environ["M02_STAGING"] = str(staging_dir)
    os.environ["M02_AUTH_FILE"] = str(staging_dir / "auth.json")
    os.environ["M02_CONFIG_FILE"] = str(staging_dir / "config.json")
    os.environ["M02_LOG_FILE"] = str(staging_dir / "scraper.log")

    pushed_calls = []
    stub = types.ModuleType("store_client")

    def _push_media(folder, path, stem, date_iso, is_out=False):
        pushed_calls.append({"folder": folder, "path": path, "stem": stem})
        return {"ok": True}

    def _get_folder_meta():
        return {"redirects": {}}

    stub.push_media = _push_media
    stub.get_folder_meta = _get_folder_meta
    sys.modules["store_client"] = stub

    sys.path.insert(0, str(FILES_DIR))
    mod_name = "scraper_wrapper"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import scraper_wrapper as mod  # noqa: PLC0415 — deliberate late/fresh import
    return mod, pushed_calls


def test_growing_file_not_pushed_until_size_stable():
    """The regression this gate exists for: a file that's still being written
    (size changing between polls) must NOT be pushed. Confirmed against a
    live re-run after the FIRST fix attempt (a fixed mtime-grace window) was
    found to still push a growing file 3x, ~11-12s apart -- a real download
    can have idle gaps longer than any small time window it's safe to guess.
    This test locks in the size-comparison replacement instead."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mod, pushed = _import_module_fresh(td)
        model_dir = td / "somemodel"
        model_dir.mkdir()
        f = model_dir / "clip.mp4"

        # Tick 1: file just appeared (simulates the download's first bytes).
        f.write_bytes(b"a" * 100)
        p, failed, skipped = mod._walk_and_push()
        if pushed:
            raise AssertionError(f"must not push on first sighting, got {pushed!r}")
        if p != 0 or skipped != 1:
            raise AssertionError(f"expected 0 pushed/1 skipped, got pushed={p} skipped={skipped}")

        # Tick 2: file grew (still downloading) -> still must not push, even
        # though this is its SECOND observation (this is exactly the case the
        # old mtime-based gate got wrong for a slow/bursty download).
        f.write_bytes(b"a" * 500)
        p, failed, skipped = mod._walk_and_push()
        if pushed:
            raise AssertionError(f"must not push a still-growing file, got {pushed!r}")
        if p != 0 or skipped != 1:
            raise AssertionError(f"expected 0 pushed/1 skipped on growth tick, got pushed={p} skipped={skipped}")

        # Tick 3: size identical to tick 2 -> now stable, must push exactly once.
        p, failed, skipped = mod._walk_and_push()
        if len(pushed) != 1:
            raise AssertionError(f"expected exactly 1 push once size is stable, got {pushed!r}")
        if p != 1 or failed != 0:
            raise AssertionError(f"expected pushed=1 failed=0, got pushed={p} failed={failed}")
        if f.exists():
            raise AssertionError("pushed file must be deleted from staging (existing contract)")


def test_stable_file_pushed_exactly_once_not_repeatedly():
    """Direct regression for the live symptom: same stem pushed 2-3 times per
    download. Once a file is stable and pushed, it's gone (unlink) -- a
    subsequent tick over an now-empty staging dir must push nothing more."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mod, pushed = _import_module_fresh(td)
        model_dir = td / "somemodel"
        model_dir.mkdir()
        f = model_dir / "photo.jpg"
        f.write_bytes(b"x" * 200)

        mod._walk_and_push()  # tick 1: first sighting, recorded, not pushed
        mod._walk_and_push()  # tick 2: size unchanged -> pushed + unlinked
        mod._walk_and_push()  # tick 3: nothing left in staging

        if len(pushed) != 1:
            raise AssertionError(f"expected exactly ONE push total across 3 ticks, got {pushed!r}")


def test_seen_sizes_cleared_after_push_no_leak_on_reused_path():
    """If a NEW file later reuses the same path (staging dir recycled — the
    scraper always deletes+re-creates rather than reusing names in practice,
    but the internal bookkeeping should not silently assume that), the size
    tracker must not carry stale state that could cause a wrong push/skip
    decision."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mod, pushed = _import_module_fresh(td)
        model_dir = td / "somemodel"
        model_dir.mkdir()
        f = model_dir / "clip.mp4"

        f.write_bytes(b"a" * 100)
        mod._walk_and_push()  # first sighting of size 100
        mod._walk_and_push()  # stable -> pushed, unlinked, tracker entry cleared
        if str(f) in mod._SEEN_SIZES:
            raise AssertionError("_SEEN_SIZES must be cleared for a path after a successful push")
        pushed_count_before = len(pushed)

        # A new file at the exact same path, coincidentally the same starting
        # size as a mid-download snapshot the tracker might still remember --
        # must be treated as a fresh, unseen file (one skip tick), not pushed
        # immediately just because "100" was seen before.
        f.write_bytes(b"b" * 100)
        p, failed, skipped = mod._walk_and_push()
        if len(pushed) != pushed_count_before:
            raise AssertionError(
                f"stale tracker entry caused an immediate wrong push: "
                f"before={pushed_count_before} after={len(pushed)} pushed={pushed!r}")
        if p != 0 or skipped != 1:
            raise AssertionError(f"expected first sighting of the NEW file to be skipped, got pushed={p} skipped={skipped}")


def test_part_suffix_never_pushed_even_if_size_stable():
    """2026-09-21 root-cause incident: the size-comparison gate alone is not
    sufficient — a genuine mid-download stall (slow segment, throttled
    connection) can present the SAME byte count across two consecutive 5s
    polls despite the file being nowhere near finished. ofscraper writes to
    a `<name>.part` path for the full duration of the download (both the
    plain and DASH/DRM code paths) and only renames it away once complete and
    integrity-checked. A `.part` file must never be pushed, no matter how
    many ticks its size stays unchanged."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mod, pushed = _import_module_fresh(td)
        model_dir = td / "somemodel"
        model_dir.mkdir()
        f = model_dir / "big_video_12345.part"
        f.write_bytes(b"a" * 1000)  # size is irrelevant to this test; the .part suffix alone must gate it

        # Three ticks with an UNCHANGED size (the exact condition that would
        # satisfy the old gate) must still never push a .part file.
        for _ in range(3):
            p, failed, skipped = mod._walk_and_push()
            if pushed:
                raise AssertionError(f".part file must never be pushed, got {pushed!r}")
            if p != 0:
                raise AssertionError(f"expected pushed=0 for .part file, got {p}")

        # Once ofscraper renames it away (simulating download completion),
        # normal stability-gate behavior resumes: one skip tick, then pushed.
        final = model_dir / "big_video_12345.mp4"
        f.rename(final)
        mod._walk_and_push()  # first sighting of the renamed file
        mod._walk_and_push()  # stable -> pushed
        if len(pushed) != 1:
            raise AssertionError(f"expected exactly 1 push after rename away from .part, got {pushed!r}")


def main():
    print("test_scraper_wrapper: running")
    check("growing file is never pushed mid-download (the core regression)",
          test_growing_file_not_pushed_until_size_stable)
    check("stable file is pushed exactly once, not repeatedly",
          test_stable_file_pushed_exactly_once_not_repeatedly)
    check("_SEEN_SIZES cleared after push (no stale-state leak)",
          test_seen_sizes_cleared_after_push_no_leak_on_reused_path)
    check(".part files are never pushed even with a stable size",
          test_part_suffix_never_pushed_even_if_size_stable)
    print(f"test_scraper_wrapper: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
