# Gallery re-key cutover — state + handoff (2026-11-23 ~11:45 CST)

Written by the homelab session. **Do not run the cutover without reading the
"why it looks broken" section** — the owner has flagged "a LOT of missing pics".

## Where the two trees stand (measured, 11:40 CST)

| tree | remote | objects | size |
|---|---|---|---|
| live (old keys) | `gcrypt:` → `gdrive:tg-harvester` | **557,205** | 1.244 TiB |
| mirror (new keys) | `gcrypt2:` → `gdrive:tg-harvester-v2` | **521,360** | 1.208 TiB |

**The mirror is 35,845 objects / ~36 GiB behind, and it is not converging.**
The live ingest keeps writing into the old tree (~1.6k objects/h) while the
recrypt pass copies at roughly the same rate, so the gap stays flat.

## What is running

- `recrypt-gallery.service` — an `rclone copy gcrypt: gcrypt2:` pass started
  Mon 00:05, still running. `--tpslimit 8 --transfers 4 --bwlimit 40M
  --max-transfer 700G --cutoff-mode soft`. Script: `/root/recrypt/recrypt-copy.sh`,
  log `/var/log/recrypt-gallery.log`, config `/root/recrypt/gallery.conf`.
- It is driven by `recrypt-gallery.timer` (every 20 min, `flock`ed), gated by
  `recrypt-window-ok` which **blocks Fri 18:00 → Mon 00:00** so the weekend
  Drive pushes keep the 750 GB/day upload quota.
- No `/root/recrypt/gallery.DONE` — no pass has ever finished clean. Every pass
  ends on `--drive-stop-on-upload-limit`, a `sizes differ` error, or a handful
  of `unexpected EOF` uploads.

## Why it looks broken (the "missing pics")

Two independent things, do not conflate them:

1. **Mirror lag (above).** Anything cut over today would lose ~35.8k objects,
   which is very likely what the owner is reacting to. A cutover is only safe
   after a quiesced final pass plus a `check` that returns 0 differences.
2. **Thumbnail tmpfs is full.** In CT 115: `/var/lib/media-gallery/thumbcache`
   is a **6G tmpfs at 5.57 GB used (96%, 299 MB free)** holding 277,084 files,
   against 273,169 thumbs on Drive. `media-gallery-prewarm` runs hourly and
   cannot add more. This shows as blank/missing tiles in the UI even when the
   underlying file is present. Fix is a bigger tmpfs
   (`media_gallery_thumbcache_tmpfs_size`, currently `6G`) plus CT 115 memory
   (`memory: 16384`) — pve01 has 76 GB available. **Not yet changed.**

## Cutover runbook (only after the check is clean)

1. Quiesce the writer: stop the media-ingest uploads + `media-gallery-gallery`,
   confirm no `rclone copyto` to `gcrypt:` for 5 min.
2. Final pass: `rclone --config /root/recrypt/gallery.conf copy gcrypt: gcrypt2:`
   with the quota/window guards off and a raised `--tpslimit`, until rc=0.
3. Verify: `rclone check gcrypt: gcrypt2: --size-only --one-way` → must be 0
   differences (expect the known duplicate-named objects to be reported as
   duplicates, not missing).
4. Repoint: `media_gallery_gdrive_folder` → `tg-harvester-v2`, deploy
   `deploy_media_gallery.yml` + `deploy_media_ingest.yml`; restart the
   `media-gallery-*` units so the `rclone serve` remotes pick up `gcrypt2`.
5. Delete the old tree only after a day of clean operation:
   `rclone purge gcrypt: --drive-use-trash=false` (1.24 TiB; trash counts
   against quota, always pass `--drive-use-trash=false`).
6. Then drop the `*_v2` remote names and the `recrypt-gallery` timer.

## Do not

- Do not delete the old tree before the check is clean.
- Do not `rclone delete`/`deletefile` on Drive without `--drive-use-trash=false`;
  trashed objects still count against the 5 TB quota (this bit us for 136 GiB).
- Do not raise `recrypt-gallery`'s window past Friday 18:00 — the weekend pushes
  need the 750 GB/day upload cap.

## 2026-11-23 ~12:05 CST — root cause of the "missing pics": the recrypt copy itself

Owner reported chats showing ~2 images (aminahvip, ms_cece) that later came back.

Measured:
- The gallery index is complete. 283,002 manifest entries; diff against a full
  `rclone lsl gcrypt:by-chat` (283,606 objects) → **0 missing, 0 size
  mismatches, 0 zero-byte**. 617 of 619 chats indexed (2 new, next refresh).
  Nothing in the ingest/gallery path deletes media (no rclone delete/purge).
- `media-gallery-gallery` logged **5,643 `unexpected EOF` read errors** in the
  last 7 days — **3,014 on 11-22 and 2,629 on 11-23**, i.e. only once the
  re-key copy started hammering Drive. A listing that errors part-way yields a
  PARTIAL manifest, so a chat shows a couple of items until the next refresh.
- Stopped `recrypt-gallery.timer` + `recrypt-gallery.service` at 18:02 UTC.
  **0 `unexpected EOF` in the 5 minutes after** (was ~2,600/day).

Conclusion: the re-key copy competes with the app for Drive's per-user API
budget and produces partial listings. Do NOT restart it at the current rate.

### Next cutover plan (revised)
1. Leave `recrypt-gallery` STOPPED until the cutover window; it does not
   converge while ingest runs anyway (35.8k objects behind and flat).
2. Cutover window: stop the ingest writers, run ONE bounded final pass with a
   raised `--tpslimit` and no `--bwlimit`, then `rclone check --size-only
   --one-way` = 0 differences.
3. Repoint `media_gallery_gdrive_folder` → `tg-harvester-v2`, redeploy
   media_gallery + media_ingest, restart the `media-gallery-*` units.
4. Only then purge `gcrypt:` (old, 1.24 TiB) with `--drive-use-trash=false`.
5. Re-enable nothing until a day of clean operation.

### Also open
- CT 115 thumbcache tmpfs: 6G, 96% full (5.57 GB / 277,084 files) — prewarm
  cannot add thumbs. Raise `media_gallery_thumbcache_tmpfs_size` (6G→10G) and
  CT 115 memory (16G→24G); costs a cache rebuild.
- The gallery's transient partial manifests have no alert. The recrypt copy had
  no rate/budget guard either — that is why it silently degraded the app.
