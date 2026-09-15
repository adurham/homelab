#!/usr/bin/env python3
"""Plain-python tests for thumb_backfill.py's fast local generation path.

Run with:  python3 tests/test_thumb_backfill.py   (from the role dir)
No pytest dependency — plain asserts + main() that prints PASS/FAIL and exits
non-zero on failure, matching the rest of this role's test style.

thumb_backfill.py's rclone() calls hit a real subprocess; we stub it (via
monkeypatching the module-level name, same approach test_dedup_live.py uses
for save_hidden's rclone mirror) so these tests need no real Drive/rclone
access. generate_thumb_local() imports thumb_service INSIDE the function
(deliberately, see its docstring), and thumb_service.py itself binds
LOCAL_CACHE.mkdir() at import time — pointed at a temp dir via env var before
import so it never touches /var/lib/media-gallery on this machine.
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
    """(Re)import thumb_backfill + thumb_service against a temp cache dir,
    with rclone() stubbed on BOTH modules (thumb_backfill calls its own
    module-level rclone() for copyto; thumb_service's make_thumb() never
    shells out to rclone itself, only ensure_thumb() does, which this test
    doesn't exercise -- generate_thumb_local() calls make_thumb() directly).
    """
    os.environ["THUMB_LOCAL_CACHE"] = str(tmpdir / "thumbcache")
    for mod_name in ("thumb_backfill", "thumb_service"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    import thumb_backfill as tb
    return tb


def _make_test_image(path, size=(64, 64), color=(200, 50, 50)):
    from PIL import Image
    im = Image.new("RGB", size, color)
    im.save(path, "JPEG")


def test_generate_thumb_local_happy_path():
    """The core fast-path contract: given a chat/leaf/stem, download (stubbed)
    the original by its EXACT filename (no folder listing), thumbnail it via
    the real thumb_service.make_thumb, and upload (stubbed) the result."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tb = _fresh_import(td)

        # Fixture "originals" live in a fake source dir; the stubbed rclone
        # copyto/upload just copies between real local paths so the actual
        # Pillow resize logic still runs for real.
        fake_remote = td / "fake_remote"
        fake_remote.mkdir()
        orig = fake_remote / "somechat" / "photo_123x456_abcdef.jpg"
        orig.parent.mkdir(parents=True)
        _make_test_image(orig, size=(1200, 1200))

        uploaded = {}

        def fake_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
            args = list(args)
            if args[0] == "copyto":
                src, dst = args[1], args[2]
                if src.startswith(str(tb.SRC)):
                    # download: src is "gcrypt:by-chat/somechat/leaf" (fake) ->
                    # redirect to our real fixture file
                    leaf = src.split("/")[-1]
                    chat = src.split("/")[-2]
                    real_src = fake_remote / chat / leaf
                    Path(dst).write_bytes(real_src.read_bytes())
                elif dst.startswith(str(tb.THUMBS)):
                    # upload: record what would have been uploaded
                    uploaded[dst] = Path(src).read_bytes()
                return R()
            return R()

        tb.rclone = fake_rclone

        ok, size, err = tb.generate_thumb_local(
            "somechat", "photo_123x456_abcdef.jpg", "photo_123x456_abcdef", td)
        if not ok:
            raise AssertionError(f"expected success, got err={err!r}")
        if size != orig.stat().st_size:
            raise AssertionError(f"reported size {size} != original size {orig.stat().st_size}")
        expected_dst = f"{tb.THUMBS}/somechat/photo_123x456_abcdef.jpg"
        if expected_dst not in uploaded:
            raise AssertionError(f"expected upload to {expected_dst!r}, got keys {list(uploaded)!r}")
        # confirm it's a real, valid, resized JPEG -- not just bytes copied through
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(uploaded[expected_dst]))
        im.verify()
        # thumb_service.THUMB_PX=400 cap: a 1200x1200 square source must come
        # back at 400x400, not passed through at full size.
        im2 = Image.open(io.BytesIO(uploaded[expected_dst]))
        if max(im2.size) != 400:
            raise AssertionError(f"expected resize to 400px max side, got {im2.size!r}")


def test_generate_thumb_local_download_failure_reported_not_raised():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tb = _fresh_import(td)

        def failing_rclone(*args):
            class R:
                returncode = 1
                stderr = "simulated download failure"
            return R()

        tb.rclone = failing_rclone
        ok, size, err = tb.generate_thumb_local("somechat", "missing.jpg", "missing", td)
        if ok:
            raise AssertionError("expected failure to be reported, not swallowed as success")
        if err is None or "download failed" not in err:
            raise AssertionError(f"expected a download-failure message, got {err!r}")
        if size != 0:
            raise AssertionError(f"expected 0 bytes on immediate download failure, got {size}")


def test_generate_thumb_local_empty_download_reported():
    """A zero-byte 'original' (e.g. a transient Drive glitch) must be reported
    as a failure, not silently handed to make_thumb (which would raise inside
    Pillow with a much less useful error, or worse, hang/misbehave)."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tb = _fresh_import(td)

        def empty_rclone(*args):
            class R:
                returncode = 0
                stderr = ""
            args = list(args)
            if args[0] == "copyto" and args[1].startswith(str(tb.SRC)):
                Path(args[2]).write_bytes(b"")  # simulate empty download
            return R()

        tb.rclone = empty_rclone
        ok, size, err = tb.generate_thumb_local("somechat", "empty.jpg", "empty", td)
        if ok:
            raise AssertionError("empty download must not be reported as success")
        if err is None or "empty" not in err:
            raise AssertionError(f"expected an 'empty' error message, got {err!r}")


def test_video_items_still_use_http_path_not_local():
    """Regression guard for the documented scope limit: the fast local path
    is images only. This doesn't spin up a real HTTP server -- it just
    verifies main()'s branch selection would route video items away from
    generate_thumb_local (checked structurally: main() checks
    it.get("type") == "video" before choosing the local path, and this test
    would need a live server to test main() end-to-end, which is out of
    scope for a unit test -- so this test instead locks in the CONTRACT via
    a direct read of the source, catching an accidental removal of the
    is_video branch in a future edit)."""
    src = (FILES_DIR / "thumb_backfill.py").read_text()
    if 'is_video = it.get("type") == "video"' not in src:
        raise AssertionError(
            "expected an explicit is_video check gating the fast local path -- "
            "if this was refactored, make sure videos still route to the HTTP "
            "path (thumb_service's video poster logic is NOT reimplemented here)")


def main():
    print("test_thumb_backfill: running")
    check("generate_thumb_local happy path produces a real resized JPEG",
          test_generate_thumb_local_happy_path)
    check("generate_thumb_local reports (not raises) a download failure",
          test_generate_thumb_local_download_failure_reported_not_raised)
    check("generate_thumb_local reports an empty/zero-byte download",
          test_generate_thumb_local_empty_download_reported)
    check("video items still route to the HTTP path, not the fast local path",
          test_video_items_still_use_http_path_not_local)
    print(f"test_thumb_backfill: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
