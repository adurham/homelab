# media-ingest-02 — delivery verification + the "missing from gallery" number (2026-11-23 ~18:10 CST)

Written by the media-ingest-02 session. Answers the open problem in the OF-lane
handoff and records the first measured gap. No gallery changes, no SSH to the
gallery, nothing in this doc needs the re-key cutover to land first.

## The defect, restated

ofscraper flips `medias.downloaded=1` when a file lands in **staging**. That flag
never meant "in the gallery". The wrapper unlinked the staged copy on any HTTP
2xx, and three paths dropped files while the flag stayed 1: exclusion-skip
unlink, the 4h stale sweeper, and any abort/timeout. Permanent and invisible.

## What changed (roles/media_ingest_02)

1. **Verified push.** `store_client.push_media()`'s response carries
   `stored` (count accepted). `_push_verified()` treats anything but `stored>=1`
   as a FAILED push — the file is parked encrypted, never unlinked.
   Escape hatch: `M02_UPLOAD_VERIFY=false`.
2. **Upload ledger** — `/var/lib/media-ingest-02/upload_ledger.sqlite`, one row
   per stem: `verified / parked / park_failed / dropped_unstored /
   excluded_skip / missing_confirmed`, written *before* the unlink.
3. **Sweep-start drain** — `main()` pushes leftovers from an aborted sweep
   *before* the stale sweeper can touch them (`force_old_sec=600`; no scraper is
   running yet, so the size gate's second observation is unnecessary).
4. **No more silent drops** — every path that drops a staged file without a
   verified store records it and resets `medias.downloaded=0`, so the next
   sweep really re-downloads it. Orphaned `.part` files are dropped without a
   reset (they were never complete).
5. **`--audit`** — per-model backlog report (`verified / known_gap /
   unverified`) against the ledger. `--reset-known-gaps` re-queues known gaps.
6. **`--reconcile [--apply]`** — asks the gallery.

## The inventory question is answered: POST /ingest/have

`upload_service.py` already exposes `POST /ingest/have {"stems":[...]}` →
`{"have":[...]}`, where "have" = the ingest datemap (**every stem ever
ingested**) ∪ the exclusion ledger. `store_client.have_stems()` wraps it
(chunks of 4000). No SSH, no Drive listing, no new endpoint.

`/ingest/excluded` was never an inventory (delete-only list) — `/ingest/have`
is the one that answers "do you have it".

Caveat, stated plainly: the datemap is written when the gallery **accepts** an
upload (staging + datemap), before its async GDrive pusher runs. So `/have`
cannot see a file the gallery accepted and then failed to push to Drive. That
blind spot only a Drive/rclone listing closes (gallery-01, 100.83.114.12 — SSH
refused for this workstation; and see the cutover doc: the mirror is 35.8k
objects behind, thumbnail tmpfs 96% — a blank tile is not necessarily a missing
file).

## The number (measured live, 2026-11-23 18:00 CST)

| | |
|---|---|
| downloaded rows with no staged file | 379,656 |
| gallery accounts for | 359,894 |
| **genuinely missing** | **6,901 across 121 models** |
| composition | 6,352 images · 541 videos · 8 audio |
| spread | every month 2019-12 → 2026-11 (not one bad period) |
| worst models | womanwearingred 1199 · vi.thehamburger 692 · ruby_kingsley 428 · yunikki 381 · janedxd 263 |

Applied at 18:05: all 6,901 reset to `downloaded=0` (verified per-model:
womanwearingred went 1,199 → 0 pending rows), each recorded as
`missing_confirmed` in the ledger. Next sweeps re-fetch them through the new
verified path.

This replaces the earlier ms_cece/aminahvip reset, which was based on
`/ingest/excluded` — that measurement was junk (harmless reset, but not surgical).

## Still open

- The 6,901 are queued, not recovered. Watch `reconcile_report.json`; a second
  pass after a few sweeps should show the count falling, and any residual is
  media the source no longer serves (deleted posts, expired purchases).
- `parked`/`park_failed` rows in the ledger need the private park key (1P) to
  recover. Nothing reads that path automatically yet.
- Optional: prune the dead usernames (sexytestmi, quadmomcrush, bigb00ti3ho3,
  purchased:u#######) from `vault_media_ingest_02_scrape_usernames` — ~86
  subprocess launches/day, no functional impact.
