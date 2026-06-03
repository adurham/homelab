#!/usr/bin/env python3
"""
Bulk-ingest helper for the TG gallery — the FAST lane for the initial thousands.

Run on a machine that has rclone configured with the crypt remote (your Mac uses
remote 'tgcrypt:'; the CT uses 'gcrypt:'). Point it at a LOCAL folder of decrypted
images/videos; it:
  1. renames each into an "up_<ms>_<rand>.<ext>" stem (collision-proof, marks it
     as an upload so the manifest never source-fetches it)
  2. records EXIF DateTimeOriginal (or file mtime) per item
  3. rclone-copies the batch into <remote>by-chat/<Folder>/  (encrypted, parallel)
  4. merges the dates into the datemap so they sort correctly mixed with
     source media, then triggers a manifest rebuild.

Because the datemap + manifest live on the CT, this writes the new dates to a
sidecar JSON and (by default) ships it to the CT + kicks a rebuild over SSH.
You can also run with --remote-side on the CT itself.

Usage (on the Mac):
  python3 bulk_ingest.py --src ~/Pictures/person1-export --folder person1 --remote tgcrypt: \\
      --ssh root@media-gallery-01.tail19c543.ts.net

  --dry-run        show what would happen, copy nothing
  --remote NAME    rclone remote (default tgcrypt: on Mac, gcrypt: on CT)
  --ssh TARGET     CT ssh target to merge datemap + rebuild (omit if running on CT)
  --workers N      rclone --transfers (default 8)
"""
import argparse
import datetime as dt
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
DATEMAP_REMOTE_PATH = "/var/lib/media-gallery/datemap.json"


def log(*a):
    print(*a, flush=True)


def exif_date(path):
    if not HAVE_PIL:
        return None
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            for tag in (36867, 306):
                v = ex.get(tag)
                if v:
                    return dt.datetime.strptime(str(v), "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:  # noqa: BLE001
        pass
    return None


def new_stem():
    return f"up_{int(time.time()*1000)}_{secrets.token_hex(4)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="local folder of decrypted media")
    ap.add_argument("--folder", required=True, help="destination gallery folder (e.g. person1)")
    ap.add_argument("--remote", default="tgcrypt:", help="rclone crypt remote")
    ap.add_argument("--ssh", default="", help="CT ssh target to merge datemap + rebuild")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(os.path.expanduser(args.src))
    if not src.is_dir():
        log(f"src not a directory: {src}"); sys.exit(1)
    folder = "".join(c if c.isalnum() or c in " -_" else "" for c in args.folder).strip().replace(" ", "-")
    if not folder:
        log("bad folder name"); sys.exit(1)

    files = [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in (IMAGE_EXT | VIDEO_EXT)]
    log(f"found {len(files)} media files under {src}")
    if not files:
        sys.exit(0)

    work = Path(tempfile.mkdtemp(prefix="bulk_ingest_"))
    datemap_add = {}
    log(f"staging into {work} with up_ stems...")
    for p in files:
        stem = new_stem()
        ext = p.suffix.lower()
        date = exif_date(p) or dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat()
        datemap_add[stem] = {"date": date, "out": False, "src": "upload"}
        if not args.dry_run:
            # hardlink if same fs (instant), else copy
            dest = work / f"{stem}{ext}"
            try:
                os.link(p, dest)
            except OSError:
                shutil.copy2(p, dest)

    log(f"prepared {len(datemap_add)} items for folder '{folder}'")
    if args.dry_run:
        log("DRY RUN — nothing uploaded. Sample stems:")
        for s in list(datemap_add)[:5]:
            log(f"   {s}  date={datemap_add[s]['date']}")
        shutil.rmtree(work, ignore_errors=True)
        return

    dest_remote = f"{args.remote}by-chat/{folder}"
    log(f"rclone copy -> {dest_remote} ({args.workers} transfers)...")
    r = subprocess.run(
        ["rclone", "copy", str(work), dest_remote,
         "--transfers", str(args.workers), "--checkers", str(args.workers * 2),
         "--progress", "--retries", "5", "--low-level-retries", "10"],
    )
    shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        log("rclone copy FAILED"); sys.exit(1)
    log("upload complete.")

    # write the date sidecar and merge into the CT datemap
    sidecar = Path(tempfile.gettempdir()) / f"datemap_add_{int(time.time())}.json"
    sidecar.write_text(json.dumps(datemap_add))
    log(f"date sidecar: {sidecar} ({len(datemap_add)} entries)")

    if args.ssh:
        log(f"merging datemap on {args.ssh} + rebuilding manifest...")
        # ship sidecar, merge into datemap.json, rebuild
        subprocess.run(f"cat {sidecar} | ssh {args.ssh} 'cat > /tmp/datemap_add.json'",
                       shell=True, check=True)
        merge_cmd = (
            "python3 -c \""
            "import json;"
            f"p='{DATEMAP_REMOTE_PATH}';"
            "d=json.load(open(p));a=json.load(open('/tmp/datemap_add.json'));"
            "d.update(a);json.dump(d,open(p,'w'));"
            "print('datemap merged:',len(d))\""
        )
        subprocess.run(
            f"ssh {args.ssh} \"chown mediaingest:mediaingest /tmp/datemap_add.json; "
            f"sudo -u mediaingest {merge_cmd}; "
            f"sudo -u mediaingest env RCLONE_CONFIG=/home/mediaingest/.config/rclone/rclone.conf "
            f"TG_RCLONE_REMOTE=gcrypt: /opt/media-gallery/venv/bin/python "
            f"/opt/media-gallery/build_manifest.py; rm -f /tmp/datemap_add.json\"",
            shell=True, check=False)
        sidecar.unlink(missing_ok=True)
        log("DONE — gallery updated.")
    else:
        log(f"NOTE: not merged. On the CT, merge {sidecar} into {DATEMAP_REMOTE_PATH} "
            f"and run build_manifest.py.")


if __name__ == "__main__":
    main()
