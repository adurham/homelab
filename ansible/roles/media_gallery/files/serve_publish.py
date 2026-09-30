"""Shared helper for the LOCAL tmpfs serve mirror of gallery metadata.

WHY THIS EXISTS (2026-09-30): every SPA page load fetches manifest.json
(~85MB uncompressed), and the browser-facing path used to stream that file
straight from Google Drive through `rclone serve http gcrypt:` — ~10s of WAN
round-trip per load, measured. The same bytes served from a local RAM tmpfs
cost ~0.2s (measured). Several long-running services also re-fetched the
manifest from Drive on a timer (thumb_service every ~5 min, dedup_scan and
thumb_backfill per run), so the same 85MB was crossing the wire dozens of
times a day for no reason.

This module is the single place that knows how to:
  - publish_local(src, name)  — put a freshly built metadata file into the
    serve dir (tmpfs) that lb-01 routes the browser's metadata fetches to.
  - read_local(name)          — read that local copy when it exists.
  - stage_manifest(dest, ...) — materialize the freshest manifest.json at
    `dest`: local copy if present, else a Drive fetch (exactly the old
    behavior). Callers keep their existing Drive fallback automatically.

SAFETY: publish_local refuses to write unless the target is an active mount,
so decrypted metadata can never silently land on the CT's disk if the tmpfs
is not up. It also bumps the file mtime strictly monotonically, which makes
`Cache-Control: no-cache` revalidation (If-Modified-Since) airtight: a
content change always advances the validator, so a 304 can never mask
updated content.

Used by build_manifest.py, dedup_scan.py, trash_service.py (publishers) and
thumb_service.py, thumb_backfill.py (readers).
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

SERVE_DIR = Path(os.environ.get("TG_SERVE_DIR", "/var/lib/media-gallery/serve"))


def local_path(name: str) -> Path:
    return SERVE_DIR / "gallery" / name


def publish_local(src: Path, name: str, log=print) -> None:
    """Atomically publish a built metadata file into the local serve dir.

    Never raises: the Drive copy is the durable one and the boot-time seed
    restores this dir, so a publish failure only costs speed, not data.
    Refuses to write when SERVE_DIR is not a mount point (tmpfs down) so
    decrypted metadata cannot leak to the CT disk.

    The published file's mtime is bumped strictly monotonically at SECOND
    granularity (HTTP dates carry seconds), because lb-01 serves these files
    with `Cache-Control: no-cache` — the browser revalidates with
    If-Modified-Since, so a rebuild that happened within the same second as
    the copy the browser holds would otherwise be masked by a 304.
    """
    try:
        if not os.path.ismount(SERVE_DIR):
            log(f"local serve publish skipped ({name}): {SERVE_DIR} is not a mount")
            return
        d = SERVE_DIR / "gallery"
        d.mkdir(parents=True, exist_ok=True)
        target = d / name
        prev = None
        try:
            prev = target.stat().st_mtime
        except OSError:
            pass
        tmp = d / f".{name}.tmp-{os.getpid()}"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
        now = time.time()
        if prev is not None and int(now) <= int(prev):
            now = int(prev) + 1  # never let a content change keep the old validator
            os.utime(target, (now, now))
    except OSError as e:
        log(f"local serve publish skipped ({name}): {e}")


def read_local(name: str):
    """Return the local copy of a metadata file as text, or None."""
    try:
        return local_path(name).read_text()
    except (OSError, ValueError):
        return None


def stage_manifest(dest: Path, rclone_conf: str, remote: str, log=print) -> bool:
    """Make the freshest manifest.json available at `dest`.

    Prefers the local serve copy (instant, no Drive traffic); falls back to
    the historical `rclone copyto` Drive fetch when the local copy is absent
    (e.g. right after a reboot, before the seed ran). Returns True on success.
    """
    try:
        local = local_path("manifest.json")
        if local.is_file():
            shutil.copyfile(local, dest)
            return True
    except OSError:
        pass
    cmd = ["rclone"]
    if rclone_conf:
        cmd += ["--config", rclone_conf]
    cmd += ["copyto", f"{remote}gallery/manifest.json", str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"cannot fetch manifest: {r.stderr[:200]!r}")
        return False
    return True


if __name__ == "__main__":
    # Tiny CLI so ansible handlers can publish a file with the same atomic +
    # monotonic-mtime semantics: serve_publish.py <src> <name>
    import sys
    if len(sys.argv) != 3:
        print("usage: serve_publish.py <src-file> <dest-name>", file=sys.stderr)
        sys.exit(2)
    publish_local(Path(sys.argv[1]), sys.argv[2])
