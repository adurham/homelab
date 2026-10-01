#!/usr/bin/env python3
"""One-shot RECLAIM driver: delete the already-hidden duplicate copies.

WHY THIS EXISTS (user request, 2026-10-01): "Delete the redundant copies
outright after they're listed and confirmed." The hourly dedupe HIDES
non-newest duplicate members but never removes the bytes — measured 70,636
hidden stems holding ~17.9 GB that is still paid for on Drive. This driver
deletes exactly that set, safely:

SAFETY RULES (read before changing anything here):
  1. Only stems that are hidden AND are non-newest members of a CURRENT dedup
     group are eligible. A stem that is merely hidden for some other reason, or
     no longer in any group (stale), is NEVER deleted by this tool.
  2. `keep` overrides (the user's explicit unhide decisions) are excluded.
  3. Deletion goes through the app's own /trashbatch endpoint — the single
     audited path — so every stem gets an exclusion-ledger entry and a
     removal-ledger record (reason=duplicate) automatically. Never delete via
     raw rclone here; that would bypass the audit trail the user asked for.
  4. Batched + paced: one folder at a time, N stems per call, with a pause, so
     the Drive API and the CT are never hammered.
  5. DRY RUN by default. Pass --apply to actually delete. Re-running is safe:
     already-deleted stems simply fail to resolve and are skipped.

Usage:
  # see what it WOULD delete (safe)
  python3 reclaim_hidden.py
  # do it
  python3 reclaim_hidden.py --apply
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

STATE = Path("/var/lib/media-gallery")
HIDDEN = STATE / "hidden.json"
TRASH_URL = "http://172.16.0.46:8091"
SERVE = STATE / "serve" / "gallery" / "manifest.json"
# Per-call batch size. /trashbatch builds one --include per leaf and runs a
# single rclone per folder, so 300 keeps the argv sane and each call bounded.
BATCH = 300
PAUSE = 1.5          # seconds between batches
MAX_ITEMS = 0        # 0 = no cap (all eligible)


def log(*a):
    print(*a, flush=True)


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return default


def eligible_stems():
    """(hidden - keep) INTERSECT current-duplicate-group members, grouped by
    chat. See the safety rules above.

    2026-10-01 MEMORY FIX: this used to json.load() the 85MB manifest AND the
    26MB dedup.json AND hidden.json at once — measured ~1GB of Python objects,
    which pushed this 8GB CT into 100% swap under concurrent load. The
    manifest is not needed at all: dedup.json's groups already carry each
    member's `chat` inline, so we read THAT (one document) and nothing else."""
    hidden = set((_load(HIDDEN, {}).get("hidden")) or [])
    keep = set((_load(HIDDEN, {}).get("keep")) or [])
    want = hidden - keep
    out = {}
    grouped = 0
    try:
        with open(STATE / "serve" / "gallery" / "dedup.json") as f:
            d = json.load(f)
        for g in (d.get("groups") or []):
            for m in g[1:]:              # non-newest members only
                s = m.get("stem")
                if s in want:
                    out.setdefault(m.get("chat") or "", []).append(s)
                    grouped += 1
        del d
    except (OSError, ValueError):
        pass
    return out, 0, len(hidden), grouped


def post_trashbatch(chat, stems, apply_):
    body = json.dumps({
        "chat": chat,
        "stems": stems,
        "reason": "duplicate",
        "detail": "reclaim: hidden duplicate copy removal",
        "by": "reclaim_hidden",
    }).encode()
    # curl (not urllib): urllib's timeout bounds each read, not the whole
    # transfer — a stalled peer hung a sibling sweep for 80+ minutes on this
    # box (2026-10-01). curl --max-time is a hard wall-clock cap, and -sS
    # keeps the failure message visible.
    r = subprocess.run(
        ["curl", "-fsS", "--max-time", "280", "--retry", "2",
         "--retry-delay", "3", "-X", "POST",
         "-H", "Content-Type: application/json", "--data-binary", "@-",
         f"{TRASH_URL}/trashbatch"],
        input=body, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise IOError(f"trashbatch curl rc={r.returncode}: {r.stderr[:200]!r}")
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry run, report only)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--max-items", type=int, default=MAX_ITEMS,
                    help="cap total deletes this run (0 = no cap)")
    args = ap.parse_args()

    by_chat, skipped_unknown, n_hidden, n_grouped = eligible_stems()
    total = sum(len(v) for v in by_chat.values())
    if args.max_items:
        left = args.max_items
        capped = {}
        for chat, stems in sorted(by_chat.items(), key=lambda kv: -len(kv[1])):
            if left <= 0:
                break
            take = stems[:left]
            capped[chat] = take
            left -= len(take)
        by_chat = capped
        total = sum(len(v) for v in by_chat.values())
    log(f"hidden={n_hidden} in-dup-groups={n_grouped} "
        f"eligible(hidden∧group, minus keep)={total} across {len(by_chat)} folders")
    log(f"skipped (hidden but not in manifest): {skipped_unknown}")
    if not args.apply:
        log("DRY RUN — nothing deleted. Top folders by count:")
        for chat, stems in sorted(by_chat.items(), key=lambda kv: -len(kv[1]))[:12]:
            log(f"   {len(stems):6d}  {chat}")
        log(f"\nwould delete {total} files. Re-run with --apply to execute.")
        return 0

    done = failed = 0
    t0 = time.time()
    for ci, (chat, stems) in enumerate(sorted(by_chat.items(),
                                             key=lambda kv: -len(kv[1])), 1):
        for i in range(0, len(stems), args.batch):
            chunk = stems[i:i + args.batch]
            # The trash service can be briefly saturated by a large batch in
            # flight (it serializes on its internal lock) — a single
            # connection-refused must not cost a whole 400-file chunk. Retry
            # with backoff before declaring the batch failed.
            res = None
            last_err = None
            for attempt in range(4):
                try:
                    res = post_trashbatch(chat, chunk, True)
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    time.sleep(2 + 3 * attempt)
            if res is None:
                failed += len(chunk)
                log(f"  [{ci}/{len(by_chat)}] {chat}: BATCH FAILED after retries "
                    f"({type(last_err).__name__}: {last_err}) — will be retried "
                    f"on the next run (already-deleted stems skip)")
                continue
            d = int(res.get("deleted") or 0)
            done += d
            failed += max(0, len(chunk) - d)
            log(f"  [{ci}/{len(by_chat)}] {chat}: {d}/{len(chunk)} deleted "
                f"(running total {done}, {time.time()-t0:.0f}s)")
            time.sleep(args.pause)
    log(f"RECLAIM DONE: {done} deleted, {failed} failed/skipped, "
        f"{time.time()-t0:.0f}s")
    log("The manifest rebuild + exclusion ledger are handled by /trashbatch; "
        "each stem also has a reason=duplicate record in the removal ledger.")
    # spot-verify via the ledger API
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "60",
             f"{TRASH_URL}/deletions?reason=duplicate&limit=1"],
            capture_output=True, timeout=120)
        if r.returncode == 0:
            summ = json.loads(r.stdout).get("summary") or {}
            log(f"ledger summary now: {summ}")
    except Exception as e:  # noqa: BLE001
        log(f"(ledger verify skipped: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
