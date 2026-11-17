#!/usr/bin/env bash
# Rebuild the gallery manifest and materialize the free/VIP merges.
#
# Deliberately NOT under the shared maintenance lock. This is the path that makes
# new uploads visible (the SPA reads folders_meta/folders/manifest), and it used
# to sit inside the same chain as the heavy jobs — so a reclaim/video stage that
# held that lock for an hour (including the time it spent merely POLLING for
# load headroom) also kept new media out of the gallery for an hour. It only
# lists the archive and writes JSON, so it is safe beside a reclaim stage: worst
# case a just-deleted item lingers in the manifest until the next run.
#
# auto_merge runs right after the folder list is published, so a newly-ingested
# free/vip pair appears merged within this interval instead of waiting for the
# hourly duplicate scan to finish.
set -uo pipefail

DIR=/opt/media-gallery
LOG=/var/log/media-gallery/manifest.log
LOCK=/var/lock/media-gallery-manifest.lock
export RCLONE_CONFIG=/home/mediagallery/.config/rclone/rclone.conf
export TG_RCLONE_REMOTE=gcrypt:

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1

# -n: fail fast. A slow manifest run must not queue a pile of overlapping ones,
# and the next timer tick re-runs it anyway.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "=== manifest $(date -Is): SKIPPED, previous run still in progress ==="
  exit 0
fi

echo "=== manifest $(date -Is) ==="
"$DIR/venv/bin/python" "$DIR/build_manifest.py" || echo "manifest build failed"

# Free/VIP pairs -> the merges ledger. Reads the folder list published above and
# POSTs to the upload service, which owns that ledger (this never writes it).
# Idempotent: "no change" and no write on a steady run.
"$DIR/venv/bin/python" "$DIR/auto_merge.py" || echo "auto merge failed"

echo "=== manifest done $(date -Is) ==="
