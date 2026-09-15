#!/usr/bin/env python3
"""Plain-python tests for upload_service.py's pure/near-pure helpers.

Run with:  python3 tests/test_upload_service.py   (from the role dir)
No pytest dependency — plain asserts + main() that prints PASS/FAIL and exits
non-zero on failure, matching test_dedup_live.py / test_merge_redirect.py.

Importing upload_service.py directly would try to bind a live HTTP server and
read several required env vars (INGEST_AUDIENCE, RCLONE_CONFIG, etc.) at
module level, none of which belong in a unit test. Instead we exec just the
two pure functions under test (safe_ext, sniff_media_ext) out of the source
file's AST, matching the "test the pure logic in isolation" approach already
used by test_folder_dupe_audit.py for functions with heavy module-level
side-effecting imports.
"""
import ast
import sys
import tempfile
import traceback
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"
SRC = FILES_DIR / "upload_service.py"

# Pull out just the pieces sniff_media_ext/safe_ext need: the two constant
# sets and the two function defs. Executed in an isolated namespace so we
# never trigger upload_service's module-level server/env-var setup.
_ns = {"os": __import__("os"), "Path": Path}
_tree = ast.parse(SRC.read_text())
_wanted = {"IMAGE_EXT", "VIDEO_EXT", "safe_ext", "sniff_media_ext"}
_keep = [n for n in _tree.body if (
    (isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in _wanted for t in n.targets))
    or (isinstance(n, ast.FunctionDef) and n.name in _wanted)
)]
exec(compile(ast.Module(body=_keep, type_ignores=[]), str(SRC), "exec"), _ns)  # noqa: S102 — test-only extraction of pure functions, not untrusted input
safe_ext = _ns["safe_ext"]
sniff_media_ext = _ns["sniff_media_ext"]


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


def _write(data: bytes) -> Path:
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(data)
    f.close()
    return Path(f.name)


def test_safe_ext_recognized_and_fallback():
    if safe_ext("photo.JPG") != ".jpg":
        raise AssertionError("case-insensitive image ext should normalize")
    if safe_ext("clip.mp4") != ".mp4":
        raise AssertionError("recognized video ext should pass through")
    if safe_ext("weird_temp_file_no_ext") != ".bin":
        raise AssertionError("unrecognized/missing ext must fall back to .bin")
    if safe_ext("audio.mp3") != ".bin":
        raise AssertionError(".mp3 is not in IMAGE_EXT|VIDEO_EXT -> must be .bin")


def test_sniff_recovers_real_image_types():
    cases = {
        b"\xff\xd8\xff\xe0" + b"\x00" * 20: ".jpg",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 20: ".png",
        b"GIF89a" + b"\x00" * 20: ".gif",
        b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 10: ".webp",
    }
    for data, expect in cases.items():
        p = _write(data)
        try:
            got = sniff_media_ext(p)
            if got != expect:
                raise AssertionError(f"{data[:12]!r} -> expected {expect!r}, got {got!r}")
        finally:
            p.unlink()


def test_sniff_recovers_real_video_types():
    """Regression for the live bug: a .bin video was fed to dhash() as if it
    were a photo (dedup_live checks `ext in VIDEO_EXT` using the FILENAME
    extension, which was wrong for every one of the 8568 .bin files found
    live). Confirmed against real staged files: isom/iso2/mp41/mp42/qt brands
    are all genuine playable video, never audio-only, in this pipeline."""
    cases = {
        b"\x00\x00\x00\x20ftypisom" + b"\x00" * 10: ".mp4",
        b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 10: ".mp4",
        b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 10: ".mp4",
        b"\x1aE\xdf\xa3" + b"\x00" * 20: ".webm",
        b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 10: ".avi",
    }
    for data, expect in cases.items():
        p = _write(data)
        try:
            got = sniff_media_ext(p)
            if got != expect:
                raise AssertionError(f"{data[:12]!r} -> expected {expect!r}, got {got!r}")
        finally:
            p.unlink()


def test_sniff_never_misidentifies_audio_as_video():
    """M4A/M4B are ISO-base-media containers too (same 'ftyp' box), but they
    are audio, not video. Must return None (stay .bin) rather than guess
    wrong -- sniff_media_ext's contract is 'only recover certain cases',
    never 'guess and sometimes be wrong'."""
    for brand in (b"M4A ", b"M4B "):
        data = b"\x00\x00\x00\x20ftyp" + brand + b"\x00" * 10
        p = _write(data)
        try:
            got = sniff_media_ext(p)
            if got is not None:
                raise AssertionError(f"M4A/M4B must not be reclassified as video, got {got!r}")
        finally:
            p.unlink()


def test_sniff_returns_none_for_genuinely_unknown_bytes():
    for data in (b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\x0c", b"", b"\x00" * 5):
        p = _write(data)
        try:
            got = sniff_media_ext(p)
            if got is not None:
                raise AssertionError(f"unknown/short bytes must return None, got {got!r}")
        finally:
            p.unlink()


def test_sniff_missing_file_returns_none():
    if sniff_media_ext(Path("/nonexistent/path/does/not/exist.bin")) is not None:
        raise AssertionError("missing file must return None, not raise")


def main():
    print("test_upload_service: running")
    check("safe_ext recognized types + .bin fallback", test_safe_ext_recognized_and_fallback)
    check("sniff_media_ext recovers real image types", test_sniff_recovers_real_image_types)
    check("sniff_media_ext recovers real video types (the live bug)", test_sniff_recovers_real_video_types)
    check("sniff_media_ext never misidentifies M4A/M4B audio as video", test_sniff_never_misidentifies_audio_as_video)
    check("sniff_media_ext returns None for genuinely unknown bytes", test_sniff_returns_none_for_genuinely_unknown_bytes)
    check("sniff_media_ext handles a missing file gracefully", test_sniff_missing_file_returns_none)
    print(f"test_upload_service: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
