"""Tiny textfile-collector writer shared by collector.py and reconcile.py.

Each writer owns one .prom file in METRICS_DIR; the host's metrics agent scrapes
the directory. Writing is best-effort: a metrics failure must never break
capture, so every error is swallowed. No identifiers ever go in here -- counts
and timestamps only.
"""
import fcntl
import os
import time
from pathlib import Path

METRICS_DIR = Path(os.environ.get("TG_METRICS_DIR", "/var/lib/media-ingest-metrics"))


def staging_usage(staging: Path):
    """(used_bytes, size_bytes) of the staging filesystem, or (0, 0)."""
    try:
        st = os.statvfs(str(staging))
        size = st.f_blocks * st.f_frsize
        return size - st.f_bavail * st.f_frsize, size
    except OSError:
        return 0, 0


def parked_count(failed: Path) -> int:
    """Items waiting in the park dir (one .json sidecar per item)."""
    try:
        return sum(1 for _ in failed.glob("*.json"))
    except OSError:
        return 0


def write(name: str, values: dict) -> None:
    """Atomically write {metric: number} as <name>.prom."""
    try:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = METRICS_DIR / (name + ".prom.tmp")
        body = "".join(f"{k} {float(v):.0f}\n" for k, v in sorted(values.items()))
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, METRICS_DIR / (name + ".prom"))
    except Exception:  # noqa: BLE001
        pass


def now() -> float:
    return time.time()


def stem_files(directory: Path, stem: str):
    """Files in `directory` that belong to exactly this stem.

    A bare `glob(stem + "*")` is a PREFIX match: the files of message 3073
    also match 30734. Every delete in this pipeline keys on a stem, so an
    unanchored match can remove a different item's only copy. Belonging means
    the name is the stem itself, or the stem followed by an extension
    (".jpg", ".jpg.gpg", ".json") or by the source library's duplicate suffix
    (" (1).jpg").
    """
    out = []
    try:
        for p in directory.glob(stem + "*"):
            rest = p.name[len(stem):]
            if rest == "" or rest[0] in ". ":
                out.append(p)
    except OSError:
        pass
    return out


class StemLock:
    """Advisory per-item lock shared by the live collector and the sweep.

    They are separate processes working on the same staged and parked files;
    without this the sweep can push or delete an item the collector is in the
    middle of pushing. Lock files are dot-files in the staging dir (RAM), so
    stem matching never sees them.
    """

    def __init__(self, staging: Path, stem: str):
        self.path = staging / (".lock-" + stem)
        self.fd = None

    def acquire(self, blocking: bool = False) -> bool:
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            # The previous holder unlinks the file on release; a lock taken on
            # that orphaned inode excludes nobody.
            if os.fstat(self.fd).st_ino != os.stat(str(self.path)).st_ino:
                raise OSError("stale lock file")
            return True
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            return False

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            os.unlink(str(self.path))
        except OSError:
            pass
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None
