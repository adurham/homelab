#!/bin/bash
# Managed by Ansible — roles/media_ingest_02. Do not edit by hand.
#
# Periodic disk housekeeping for the secondary collector CT. Root cause this
# exists (2026-10-08): the CT's 8G rootfs sat at 78% used, trending steadily
# down from ~5.4G free to 1.8G free over ~70 days. The two biggest reclaimable
# consumers were both inside the scraper's own state tree:
#
#   1. Per-model SQLite backup rings. The upstream scraper takes a rotating
#      backup of each model's user_data.db (ring of 5, one per day max, and it
#      also pins a copy at first run so a fresh model keeps at least one).
#      Measured live: 1,645 ring copies beyond each model's newest, ~6.0G
#      apparent. The newest copy per model is kept so a mid-migration state is
#      still recoverable; older ones are pruned.
#   2. An apt archive cache (~337MB) that nothing on this box ever prunes.
#
# Safety rules baked in (each learned the hard way elsewhere):
#   * Age gate, not a service-state gate. "Skip while the scrape service is
#     active" starves forever on a box whose sweeps are long relative to the
#     timer. A file untouched for PRUNE_AGE_DAYS cannot be the backup a
#     currently-running sweep is writing — newest-first ordering plus the age
#     gate is inherently safe and never starves.
#   * Deleting a ring file is a `rm`, never `find -delete` on a pattern that
#     could also match the live `user_data.db`. The glob is explicitly
#     `user_data_copy_*` inside a `backup/` dir. The live DB and the newest
#     copy are always skipped.
#   * The upstream's own `old_schema_*` transition backups are NEVER touched
#     (they are the only pre-migration safety copy; 433 files, ~40MB, left
#     alone deliberately).
#   * Logs the exact bytes reclaimed so the next run's numbers are verifiable
#     against df.
set -uo pipefail

META_DIR="${M02_METADATA_DIR:-/var/lib/media-ingest-02/metadata}"
LOG_FILE="${M02_HOUSEKEEPING_LOG:-/var/log/media-ingest-02/housekeeping.log}"
# Only prune ring copies that have not been touched for this many days. The
# live sweep writes its backup in one shot; 3 days is far beyond any plausible
# in-flight write, so this can never race a running download.
PRUNE_AGE_DAYS="${M02_HOUSEKEEPING_AGE_DAYS:-3}"
# Keep the newest N ring copies per model regardless of age.
KEEP_NEWEST="${M02_HOUSEKEEPING_KEEP:-1}"

mkdir -p "$(dirname "$LOG_FILE")"
exec >>"$LOG_FILE" 2>&1
echo "=== housekeeping start $(date -Is) ==="

reclaimed=0
reclaimed_files=0

# ─── 1. Per-model DB backup rings ────────────────────────────────────────────
if [ -d "$META_DIR" ]; then
  while IFS= read -r -d '' bdir; do
    # newest-first list of this model's ring copies
    mapfile -t ring < <(ls -1t "$bdir"/user_data_copy_*.db 2>/dev/null)
    n=${#ring[@]}
    if [ "$n" -le "$KEEP_NEWEST" ]; then
      continue
    fi
    for f in "${ring[@]:$KEEP_NEWEST}"; do
      # age gate: -mtime +N means untouched for MORE than N days
      if [ -n "$(find "$f" -maxdepth 0 -mtime +"$PRUNE_AGE_DAYS" 2>/dev/null)" ]; then
        sz=$(stat -c '%s' "$f" 2>/dev/null || echo 0)
        if rm -f -- "$f" 2>/dev/null; then
          reclaimed=$((reclaimed + sz))
          reclaimed_files=$((reclaimed_files + 1))
        fi
      fi
    done
  done < <(find "$META_DIR" -mindepth 2 -maxdepth 2 -type d -name backup -print0 2>/dev/null)
fi
echo "db-backup rings: reclaimed $reclaimed_files files, $((reclaimed / 1048576)) MiB (keep newest $KEEP_NEWEST, older than ${PRUNE_AGE_DAYS}d)"

# ─── 2. apt archive cache ────────────────────────────────────────────────────
apt_before=$(du -sm /var/cache/apt/archives 2>/dev/null | awk '{print $1}')
apt-get clean -qq 2>/dev/null || true
apt_after=$(du -sm /var/cache/apt/archives 2>/dev/null | awk '{print $1}')
echo "apt cache: ${apt_before:-0} MiB -> ${apt_after:-0} MiB"

echo "=== housekeeping done $(date -Is) (db-backup MiB reclaimed: $((reclaimed / 1048576))) ==="
