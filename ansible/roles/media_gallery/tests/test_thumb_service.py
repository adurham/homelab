#!/usr/bin/env python3
"""Plain-python tests for thumb_service.py's manifest-backed filename index
(find_original / _manifest_index / the stale-index retry in ensure_thumb).

Run with:  python3 tests/test_thumb_service.py   (from the role dir)
No pytest dependency — plain asserts + main() that prints PASS/FAIL and exits
non-zero on failure, matching the rest of this role's test style.

thumb_service.py binds LOCAL_CACHE.mkdir() and imports PIL at module level,
and rclone() shells out for real; we point THUMB_LOCAL_CACHE at a temp dir
and monkeypatch the module-level rclone() before exercising anything, same
approach test_dedup_live.py uses for save_hidden's rclone mirror.
"""
import json
import os
import sys
import tempfile
import traceback
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


def _fresh_import(tmpdir):
    os.environ["THUMB_LOCAL_CACHE"] = str(tmpdir / "thumbcache")
    sys.path.insert(0, str(FILES_DIR))
    if "thumb_service" in sys.modules:
        del sys.modules["thumb_service"]
    import thumb_service as ts
    # always start each test with a clean, unbuilt index cache -- module-level
    # state persists across tests within one process otherwise.
    ts._manifest_index_cache = {"index": {}, "built_at": 0.0}
    return ts


def test_manifest_index_used_when_present():
    """The core perf fix: find_original must return the manifest's exact
    leaf filename WITHOUT ever calling the expensive full-folder `rclone
    lsf` when the item is already indexed."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ts = _fresh_import(td)

        manifest = [
            {"chat": "somechat", "stem": "abc123",
             "file": "by-chat/somechat/abc123_1920x1080_deadbeef.jpg"},
            {"chat": "somechat", "stem": "def456",
             "file": "by-chat/somechat/def456_800x600_cafef00d.png"},
        ]
        listing_calls = []

        def fake_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
                stdout = ""
            args = list(args)
            if args[0] == "copyto" and args[1] == f"{ts.GALLERY}/manifest.json":
                Path(args[2]).write_text(json.dumps(manifest))
                return R()
            if args[0] == "lsf":
                listing_calls.append(args)
                r = R()
                r.stdout = "should-never-be-used.jpg\n"
                return r
            return R()

        ts.rclone = fake_rclone
        leaf = ts.find_original("somechat", "abc123")
        if leaf != "abc123_1920x1080_deadbeef.jpg":
            raise AssertionError(f"expected exact manifest leaf, got {leaf!r}")
        if listing_calls:
            raise AssertionError(
                f"find_original must NOT call the expensive folder listing "
                f"when the item is indexed, but it did: {listing_calls!r}")


def test_falls_back_to_listing_when_not_indexed():
    """An item genuinely absent from the manifest (too new, index not yet
    rebuilt since ingest) must still resolve correctly via the old, slower,
    but always-correct full-listing path -- never just return None."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ts = _fresh_import(td)

        def fake_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
                stdout = ""
            args = list(args)
            if args[0] == "copyto" and args[1] == f"{ts.GALLERY}/manifest.json":
                Path(args[2]).write_text(json.dumps([]))  # empty manifest
                return R()
            if args[0] == "lsf":
                r = R()
                # find_original's prefix match is `startswith(stem + ".")`,
                # so the leaf must literally start with "<stem>." -- confirmed
                # against the real collector's naming convention this session
                # (<stem>.<ext>, no extra fields between stem and dot).
                r.stdout = "brandnew.jpg\nother_file.jpg\n"
                return r
            return R()

        ts.rclone = fake_rclone
        leaf = ts.find_original("somechat", "brandnew")
        if leaf != "brandnew.jpg":
            raise AssertionError(f"expected fallback listing to resolve the leaf, got {leaf!r}")


def test_manifest_fetch_failure_falls_back_gracefully():
    """If the manifest itself can't be fetched (transient rclone error), the
    index build must return {} rather than raise, and find_original must
    still fall through to the real listing -- a live page-view must never
    break just because manifest.json was briefly unreachable."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ts = _fresh_import(td)

        def fake_rclone(*args):
            class R:
                returncode = 1
                stderr = "simulated transient failure"
                stdout = ""
            args = list(args)
            if args[0] == "copyto" and args[1] == f"{ts.GALLERY}/manifest.json":
                return R()  # fails
            if args[0] == "lsf":
                r = R()
                r.returncode = 0
                r.stdout = "recovered.jpg\n"
                return r
            return R()

        ts.rclone = fake_rclone
        leaf = ts.find_original("somechat", "recovered")
        if leaf != "recovered.jpg":
            raise AssertionError(f"expected graceful fallback to listing, got {leaf!r}")


def test_stale_index_entry_triggers_retry_in_ensure_thumb():
    """Direct regression for the docstring's staleness promise: if the
    manifest-index leaf no longer exists on Drive (folder merge/rename
    happened since the last manifest build), ensure_thumb must detect the
    'directory not found' failure, re-resolve via the real listing, and
    successfully complete using the CORRECTED leaf -- not just give up."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ts = _fresh_import(td)

        from PIL import Image
        real_src_dir = td / "real_source"
        real_src_dir.mkdir()
        # find_original / the retry logic both match on `startswith(stem+".")`
        # -- confirmed against the real collector's naming convention
        # (<stem>.<ext>, no extra fields between stem and dot). Use a
        # different EXTENSION between stale and real to model a genuine
        # re-ingest-with-different-format case while still exercising the
        # "leaf string actually differs" check in ensure_thumb's retry.
        real_leaf = "stem1.png"
        real_path = real_src_dir / real_leaf
        Image.new("RGB", (640, 480), (10, 20, 30)).save(real_path, "PNG")

        manifest = [{"chat": "somechat", "stem": "stem1",
                     "file": "by-chat/somechat/stem1.jpg"}]
        calls = {"copyto_attempts": []}

        def fake_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
                stdout = ""
            args = list(args)
            if args[0] == "copyto" and args[1] == f"{ts.GALLERY}/manifest.json":
                Path(args[2]).write_text(json.dumps(manifest))
                return R()
            if args[0] == "copyto" and args[1].startswith(ts.SRC):
                # the source-download attempt
                calls["copyto_attempts"].append(args[1])
                requested_leaf = args[1].split("/")[-1]
                if requested_leaf == real_leaf:
                    Path(args[2]).write_bytes(real_path.read_bytes())
                    return R()
                r = R()
                r.returncode = 3
                r.stderr = "directory not found"
                return r
            if args[0] == "copyto" and args[1].startswith(ts.THUMBS):
                return R()  # thumb cache upload, no-op success
            if args[0] == "lsf":
                r = R()
                r.stdout = f"{real_leaf}\n"  # the REAL, current filename
                return r
            if args[0] == "size":
                r = R()
                r.stdout = json.dumps({"bytes": real_path.stat().st_size})
                return r
            return R()

        ts.rclone = fake_rclone
        result = ts.ensure_thumb("somechat", "stem1")
        if result is None:
            raise AssertionError("expected ensure_thumb to recover via retry, got None")
        if not result.exists() or result.stat().st_size == 0:
            raise AssertionError(f"expected a real generated thumb at {result}")
        if len(calls["copyto_attempts"]) < 2:
            raise AssertionError(
                f"expected a failed attempt with the stale leaf THEN a retry "
                f"with the corrected leaf, got attempts={calls['copyto_attempts']!r}")
        if calls["copyto_attempts"][-1] != f"{ts.SRC}/somechat/{real_leaf}":
            raise AssertionError(
                f"expected the LAST download attempt to use the corrected leaf, "
                f"got {calls['copyto_attempts']!r}")


def test_prefer_media_leaf_skips_bin_siblings():
    """A stem can have BOTH a raw .bin download and the real .mp4 on Drive; a
    plain listing sorts .bin first, and picking it leaves the item permanently
    without a thumbnail (decode always fails). The media-extension preference
    must pick the .mp4."""
    with tempfile.TemporaryDirectory() as td:
        ts = _fresh_import(Path(td))
        listing = [
            "usatame_abc_123.bin",   # sorts first; NOT decodable
            "usatame_abc_123.mp4",   # the real file
        ]
        leaf = ts._prefer_media_leaf(listing, "usatame_abc_123")
        if leaf != "usatame_abc_123.mp4":
            raise AssertionError(f"expected the .mp4, got {leaf!r}")
        # and with only non-media siblings it must still return something
        leaf2 = ts._prefer_media_leaf(["x_1.bin"], "x_1")
        if leaf2 != "x_1.bin":
            raise AssertionError(f"expected fallback to the only candidate, got {leaf2!r}")


def test_find_original_prefers_media_extension_on_listing_fallback():
    """find_original's listing fallback must apply the same preference (this
    is the path taken for items newer than the last manifest build)."""
    with tempfile.TemporaryDirectory() as td:
        ts = _fresh_import(Path(td))

        def fake_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
                stdout = ""
            args = list(args)
            if args[0] == "copyto" and args[1] == f"{ts.GALLERY}/manifest.json":
                Path(args[2]).write_text(json.dumps([]))  # empty manifest -> fallback
                return R()
            if args[0] == "lsf":
                r = R()
                r.stdout = "stem9_100x100_aa.bin\nstem9_100x100_aa.mp4\n"
                return r
            return R()

        ts.rclone = fake_rclone
        leaf = ts.find_original("chat", "stem9_100x100_aa")
        if leaf != "stem9_100x100_aa.mp4":
            raise AssertionError(f"expected the mp4 leaf, got {leaf!r}")


def test_video_poster_http_uses_range_url_and_seek_fallback():
    """_video_poster_http must hit the /by-chat/... namespace (NOT the rclone
    remote string with its 'gcrypt:' prefix — that 404s), try -ss 1 then -ss 0,
    and return True only when a non-empty file was produced."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        ts = _fresh_import(td)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            class CP:
                returncode = 1
                stderr = b"boom"
            # succeed only on the SECOND attempt (the -ss 0 one)
            last = len([c for c in calls if c and c[0] == "ffmpeg"])
            if last >= 2:
                dst = td / "out.jpg"
                dst.write_bytes(b"jpegbytes")
                CP.returncode = 0
                CP.stderr = b""
            return CP()

        orig_run = ts.subprocess.run
        ts.subprocess.run = fake_run
        try:
            ok = ts._video_poster_http("somechat", "leaf.mp4", td / "out.jpg")
        finally:
            ts.subprocess.run = orig_run
        if not ok:
            raise AssertionError("expected the second attempt to succeed")
        first = calls[0]
        if not any(str(a).startswith(f"{ts.VIDEO_HTTP_BASE}/by-chat/somechat/leaf.mp4")
                   for a in first):
            raise AssertionError(f"expected a /by-chat/ range URL, got {first!r}")
        if any(a == "gcrypt:by-chat/somechat/leaf.mp4" for a in first):
            raise AssertionError("must not use the rclone remote string in the HTTP URL")
        seeks = [c[c.index("-ss") + 1] for c in calls if "-ss" in c]
        if seeks != ["1", "0"]:
            raise AssertionError(f"expected seek fallback 1 then 0, got {seeks!r}")


def main():
    print("test_thumb_service: running")
    check("manifest index used, expensive listing skipped when indexed",
          test_manifest_index_used_when_present)
    check("falls back to real listing when item not yet indexed",
          test_falls_back_to_listing_when_not_indexed)
    check("manifest fetch failure falls back gracefully (never raises)",
          test_manifest_fetch_failure_falls_back_gracefully)
    check("stale index entry triggers retry-with-real-listing in ensure_thumb",
          test_stale_index_entry_triggers_retry_in_ensure_thumb)
    check("media-extension preference skips .bin siblings",
          test_prefer_media_leaf_skips_bin_siblings)
    check("find_original listing fallback prefers media extensions",
          test_find_original_prefers_media_extension_on_listing_fallback)
    check("video poster uses HTTP range URL + seek fallback",
          test_video_poster_http_uses_range_url_and_seek_fallback)
    print(f"test_thumb_service: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
