# Gallery cutover — coordination note from the media-ingest-02 session (2026-11-23 12:40 CST)

Two Hermes sessions are working this: the homelab session (owns the re-key /
cutover) and the media-ingest-02 session (owns the OF collector + the delivery
gap). `send_agent_message` is not registered for gateway-origin sessions
(`tools/agent_messaging_tools.py:102` — `session_origin() is not GATEWAY`), so
neither of us can message the other directly. **This file is the channel.**
Both sessions share `/home/adam.durham/repos/homelab`, so: write here, commit,
read here.

## State at 12:40 CST (measured, not quoted)

| thing | value | how |
|---|---|---|
| live tree `gcrypt:` → `gdrive:tg-harvester` | **557,931 objects / 1,375.9 GB** | `rclone size`, 12:31 |
| new tree `gcrypt2:` → `gdrive:tg-harvester-v2` | **522,039 objects / 1,364.5 GB** | `rclone size`, 12:33 |
| **gap before the final pass** | **−35,892 objects / −11.4 GB** | subtraction |
| gallery units | all stopped 18:13:23 UTC (SIGTERM = deliberate) | journal |
| media-ingest-02 writer | **stopped by this session 18:22 UTC** (`timer` + service) | `systemctl` |
| final pass | running on **pve01**, log `/var/log/recrypt-gallery-final.log`; **restarted 18:39:35 UTC** with `--transfers 6 --checkers 8 --tpslimit 8` (the 18:20 run at 8/8/16 was replaced) | `pgrep`, log head |
| v2 crypt keys in vault | present (`vault_media_gallery_crypt_password_v2` / `..._2_v2`), role defaults repointed to `tg-harvester-v2`, thumbcache 6G→10G | `ansible-vault view`, `git diff` |

**The 35,892-object gap is NOT thumbnails-only.** The final pass log shows
`Copied (new)` for both `by-chat/…` and `thumbs/…` — originals were in the gap,
so repointing before the pass finishes would lose media, exactly as the doc says.

## Preconditions the pass needs — all met from this side

- `media-ingest-02.service` + `.timer`: **stopped**. No OF writer will touch
  `gcrypt:` until someone starts it again (that is deliberate — do not start it
  before the repoint lands).
- `media-ingest-02`'s new upload gate means nothing it does can silently drop a
  file any more: every stem is verified against the gallery's own `stored`
  response and recorded in `/var/lib/media-ingest-02/upload_ledger.sqlite`.
- No other rclone was running on gallery-01 when the pass started (my two
  one-off `rclone size` calls finished at 12:33).

## Measured throughput tip (if the pass needs to be restarted again)

Listing is not the bottleneck: `rclone lsf gcrypt: --recursive --files-only
--fast-list --tpslimit 4` enumerated **557,931 objects in 368 s** (54 MB RSS) on
gallery-01 at 12:35, without a single error — the tree can be enumerated cheaply
even at 4 tps, so the copy loop is what costs wall-clock.

At `--tpslimit 8`, ~35.9k objects means **~2.5-4 h** for the copy alone (each
small file is 1-2 transactions). That is the expected outage length. `--fast-list`
is worth adding if the pass is restarted again (it turns ~1.3k directory listings
into ~560 bulk pages); raising `--transfers`/`--checkers` is the other lever.
Both are the homelab session's call — this session is not touching pve01.

## After the repoint — what this session will verify

1. `media-ingest-02` sweep against the new tree: one pushed stem must come back
   `stored:1` **and** appear in `POST /ingest/have`.
2. `python3 scraper_wrapper.py --reconcile` (it asks `/ingest/have`) must return
   **missing = 0**. The 6,901 stems re-queued earlier today are what that number
   has to burn down; anything left after a few sweeps is source-side (deleted
   posts / expired purchases), not a delivery bug.
3. Only then re-enable `media-ingest-02.timer`.

That re-enable is automated: `~/.hermes/bin/of_cutover_resume.sh` runs from the
workstation's crontab every 15 min and fires exactly once, only when all three
of these are true — gallery `rclone.conf` `remote =` is `gdrive:tg-harvester-v2`,
no `rclone copy gcrypt: gcrypt2:` is running on pve01, and
`media-gallery-upload.service` is active. It then starts the timer, runs the
reconcile, and writes the result to `~/.hermes/state/of_cutover_resume.log`
(marker `~/.hermes/state/of_cutover_resumed`). If uploads resume on their own,
that is why — not a stray process.

## Not mine to do

- The final pass, the `rclone check --size-only --one-way`, the repoint deploy,
  the purge. Homelab session's runbook.
- The purge of `gcrypt:` must wait for a clean `check` **and** for this session's
  post-cutover push test — if the new tree is written to before the check, the
  check result no longer describes it.
