#!/usr/bin/env python3
"""Spam / ad-image finder for the media gallery (2026-10-01).

WHY OCR AND NOT PIXEL HEURISTICS: measured on real samples from this library,
generic image statistics (high-frequency energy, edge density) do NOT separate
spam from normal photos — medians were 4.1-5.7 across spam and control alike.
What actually distinguishes the junk here is TEXT: promo cards ("@user /
Subscribe"), marketing text, and UI screenshots with buttons/labels. So the
discriminator is OCR (tesseract), not a hand-wavy filter.

WHAT IT FLAGS (candidates only — NEVER deletes):
  * images whose OCR text matches promo/ad phrasing (subscribe, follow, dm me,
    subscription-site, link in bio, vip, promo, discount, giveaway, ...)
  * images that are mostly-UI (screenshot-like): detected by many short OCR
    tokens in the top/bottom bands, where app chrome tends to live
  * tiny images whose OCR is dominated by a watermark handle

REVIEW WORKFLOW (the user's chosen bar): the scanner writes
  - spam_candidates.json  (machine list: stem, chat, size, why, ocr excerpt)
  - a CONTACT SHEET (JPEG grid of the flagged thumbnails, labeled) so a human
    can eyeball everything in one image before approving anything
Nothing is hidden or deleted by this script. Approval is a separate, explicit
step (`--approve <file>`), which then hides + records in the removal ledger
with reason=spam so the audit trail shows exactly why.

Env: TESSERACT_BIN, SPAM_* knobs. Reads the local tmpfs manifest + thumbnail
cache (both already on the box) — no Drive traffic for the scan itself.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path(os.environ.get("TG_STATE_DIR", "/var/lib/media-gallery"))
SERVE = Path(os.environ.get("TG_SERVE_DIR", "/var/lib/media-gallery/serve"))
THUMB_CACHE = Path(os.environ.get("THUMB_LOCAL_CACHE", "/var/lib/media-gallery/thumbcache"))
REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "/home/mediagallery/.config/rclone/rclone.conf")
HTTP_BASE = os.environ.get("THUMB_VIDEO_HTTP_BASE", "http://172.16.0.46:8089")
OUT = Path(os.environ.get("SPAM_OUT", str(STATE / "spam_candidates.json")))
SHEET = Path(os.environ.get("SPAM_SHEET", str(STATE / "spam_review.jpg")))
TESS = os.environ.get("TESSERACT_BIN", "tesseract")
# OCR is the expensive part; budget keeps a run bounded (mirrors the backfill's
# philosophy: do real work, exit, re-run is idempotent).
DEFAULT_BUDGET = int(os.environ.get("SPAM_BUDGET", "1500"))
# Persist OCR progress every N items so a kill/OOM mid-scan loses at most this
# many items of work (2026-10-01: the full scan is 186K images / ~a day per
# slice -- losing a whole slice to a kill was wasteful; same loss class that
# bit dedup_videos). The cache+candidates file is the resumability mechanism.
SPAM_CHECKPOINT_EVERY = int(os.environ.get("SPAM_CHECKPOINT_EVERY", "250"))

PROMO_PAT = re.compile(
    r"(subscribe|follow\s+me|follow\s+for|dm\s+me|dms?\s+open|link\s+in\s+bio|"
    r"subscription-site|subscription-site|join\s+my|check\s+my|my\s+page|promo|discount|giveaway|"
    r"limited\s+time|cash\s?app|venmo|snapchat|telegram\s+me|whats?app|"
    r"new\s+video|full\s+video|watch\s+full|click\s+here|free\s+trial|"
    r"@[a-z0-9._]{3,}|\bvip\b|\bppv\b|\bsfs\b|\bf4f\b)", re.I)
UI_PAT = re.compile(
    r"\b(skip|follow|following|message|subscribe|share|save|comment|like|"
    r"send|story|reels?|explore|profile|settings|notifications?|"
    r"allow|deny|ok|cancel|continue|download|install|open\s+in\s+app)\b", re.I)


def log(*a):
    print(*a, flush=True)


def load_manifest():
    for p in (SERVE / "gallery" / "manifest.json",
              STATE / "manifest.json"):
        try:
            if p.is_file():
                return json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    log("cannot find a local manifest (serve dir or state dir) — aborting")
    sys.exit(1)


def thumb_for(item):
    """Local thumbnail path for an item (kept for the contact sheet only)."""
    chat = item.get("chat") or ""
    stem = item.get("stem") or ""
    return THUMB_CACHE / chat / f"{stem}.jpg"


def _fetch_original(item, tmpdir):
    """Download the ORIGINAL (not the thumbnail) for OCR.

    WHY: thumbnails are downscaled to ~400px, which destroys exactly the text
    this scanner looks for. Verified live 2026-10-01: thumbnail OCR of a promo
    card returned noise while OCR of the SAME original read
    `example.com/examplehandle` cleanly. The thumb is only used for the contact
    sheet (where a human eyeballs it anyway).

    Fetch via curl (not urllib): urllib's timeout bounds each read, not the
    whole transfer, and a mid-body stall hung a sibling sweep for 80+ minutes
    on this box (2026-10-01). curl --max-time is a hard wall-clock cap."""
    chat = item.get("chat") or ""
    leaf = os.path.basename(item.get("file") or "")
    if not leaf:
        return None
    ext = os.path.splitext(leaf)[1].lower() or ".img"
    dst = Path(tmpdir) / f"{item.get('stem','x')}{ext}"
    url = f"{HTTP_BASE}/by-chat/{chat}/{leaf}"
    try:
        r = subprocess.run(
            ["curl", "-fsS", "--max-time", "120", "--retry", "1",
             "--retry-delay", "2", "-o", str(dst), url],
            capture_output=True, timeout=240)
        if r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return dst
        last = f"curl rc={r.returncode} stderr={r.stderr[:160]!r}"
    except Exception as e:  # noqa: BLE001 — fall through to the rclone path
        last = f"{type(e).__name__}: {e}"
    dst.unlink(missing_ok=True)
    try:
        r = subprocess.run(
            ["rclone", "--config", RCLONE_CONF, "copyto",
             f"{REMOTE}by-chat/{chat}/{leaf}", str(dst)],
            capture_output=True, timeout=120)
        if r.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
            log(f"[spam] original unreadable {chat}/{leaf}: http={last} "
                f"rclone_rc={r.returncode}")
            return None
        return dst
    except Exception as e:  # noqa: BLE001
        log(f"[spam] original unreadable {chat}/{leaf}: http={last} "
            f"rclone={type(e).__name__}: {e}")
        return None


def ocr(path):
    """Return (text, n_tokens). Empty string when OCR fails/unavailable."""
    try:
        r = subprocess.run(
            [TESS, str(path), "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return "", 0
        t = r.stdout or ""
        return t, len([w for w in t.split() if len(w) > 1])
    except Exception:  # noqa: BLE001 — OCR failure must not stop the scan
        return "", 0


def classify(item, text, n_tokens):
    """Decide whether an item looks like spam/ad. Returns (flag, why) or
    (None, None). Deliberately conservative: the human reviews every flag."""
    low = text.lower()
    hits = sorted({m.group(0).lower() for m in PROMO_PAT.finditer(low)})
    ui_hits = sorted({m.group(0).lower() for m in UI_PAT.finditer(low)})
    size = item.get("size") or 0
    stem = (item.get("stem") or "").lower()

    if hits:
        # Strong: promo/ad wording. Require 2+ distinct hits OR one very
        # specific (subscription-site/subscribe/link in bio) so a photo that merely
        # contains the word "follow" in a caption isn't blanket-flagged.
        strong = [h for h in hits if h in ("subscription-site", "subscribe", "link in bio",
                                           "dm me", "join my", "giveaway",
                                           "cash app", "click here")]
        if len(hits) >= 2 or strong:
            return "promo_text", f"OCR promo text: {', '.join(hits[:6])}"
    if len(ui_hits) >= 3 and n_tokens <= 25 and size < 400_000:
        # Screenshot-like: a handful of UI words, small file, few tokens.
        return "ui_screenshot", f"UI-like text ({len(ui_hits)} ui tokens: {', '.join(ui_hits[:6])})"
    if "_avatar_" in stem or "_header_" in stem or "_banner_" in stem or "_pfp" in stem:
        # Profile art is usually low-value for a media archive; flag (weakly)
        # so it can be bulk-reviewed as its own class.
        return "profile_art", f"profile/header image ({len(text.split())} ocr tokens)"
    return None, None


def build_sheet(items, out_path, cols=8, cell=140):
    """Contact sheet of flagged thumbnails, labeled, for human review."""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:  # noqa: BLE001
        log(f"contact sheet skipped (PIL unavailable): {e}")
        return False
    rows = (len(items) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * (cell + 16)), (20, 20, 24))
    d = ImageDraw.Draw(canvas)
    for idx, it in enumerate(items):
        p = thumb_for(it)
        try:
            im = Image.open(p)
            im.thumbnail((cell, cell))
            x = (idx % cols) * cell
            y = (idx // cols) * (cell + 16)
            canvas.paste(im, (x, y))
            d.text((x + 2, y + cell + 2),
                   f"{it.get('chat','')[:14]}/{it.get('stem','')[:14]}",
                   fill=(210, 210, 210))
        except Exception as e:  # noqa: BLE001 — a missing/broken thumb shouldn't kill the sheet
            log(f"  sheet: skipped {it.get('stem','?')} ({type(e).__name__})")
            continue
    canvas.save(out_path, quality=78)
    log(f"contact sheet: {out_path} ({canvas.size[0]}x{canvas.size[1]}, "
        f"{len(items)} cells)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                    help="max images to OCR this run (default %d)" % DEFAULT_BUDGET)
    ap.add_argument("--rescan", action="store_true",
                    help="ignore the previous candidate file's cache and re-OCR")
    ap.add_argument("--min-size", type=int, default=None,
                    help="skip images larger than this many bytes (default: scan all)")
    ap.add_argument("--approve", metavar="FILE",
                    help="approve+hide the candidates in FILE (records them in "
                         "the removal ledger with reason=spam). NOT run by default.")
    args = ap.parse_args()

    if args.approve:
        return approve(Path(args.approve))

    manifest = load_manifest()
    items = [i for i in manifest
             if i.get("type") != "video" and not i.get("hidden")]
    # OCR every image once; cache the verdict by stem so re-runs are cheap and
    # only NEW images get the expensive pass (same pattern as the hash cache).
    cache = {}
    if not args.rescan and OUT.is_file():
        try:
            prev = json.loads(OUT.read_text())
            cache = prev.get("cache") or {}
        except (OSError, ValueError):
            cache = {}
    todo = []
    for i in items:
        if args.min_size and (i.get("size") or 0) > args.min_size:
            continue
        stem = i.get("stem") or ""
        if stem in cache:
            continue
        todo.append(i)
    todo = todo[:args.budget]
    log(f"spam scan: {len(items)} visible images, {len(cache)} cached, "
        f"{len(todo)} to OCR this run")

    flagged = []
    t0 = time.time()

    # Precompute the live-set once (write_out() reuses it), and load any
    # previous candidates so this run's flags overwrite theirs (same "current
    # wins" merge the old end-of-run code did -- just hoisted so mid-run
    # checkpoints produce identical output).
    live = {(i.get("stem"), i.get("chat")) for i in items}
    all_flagged = {}
    try:
        prev_out = json.loads(OUT.read_text()) if OUT.is_file() else {}
        for f in (prev_out.get("candidates") or []):
            all_flagged[f["stem"]] = f
    except (OSError, ValueError):
        pass

    def write_out():
        """Atomically persist candidates+cache; returns the live-filtered list."""
        cand = [f for f in all_flagged.values()
                if (f["stem"], f["chat"]) in live]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(OUT) + ".tmp"
        Path(tmp).write_text(json.dumps(
            {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "candidates": cand, "cache": cache},
            separators=(",", ":")))
        os.replace(tmp, OUT)
        return cand

    tmpdir = tempfile.mkdtemp(prefix="spamscan_")
    for n, i in enumerate(todo, 1):
        if n % SPAM_CHECKPOINT_EVERY == 0:
            try:
                write_out()
            except OSError as e:
                log(f"  (checkpoint write failed: {e}; continuing)")
        # OCR the ORIGINAL (thumbnails destroy the text — see _fetch_original)
        src = _fetch_original(i, tmpdir)
        if src is None:
            cache[i.get("stem")] = {"skip": "no-original"}
            continue
        try:
            text, toks = ocr(src)
            flag, why = classify(i, text, toks)
        finally:
            try:
                src.unlink()
            except OSError:
                pass
        cache[i.get("stem")] = {"flag": flag, "why": why, "tokens": toks,
                                "ocr": (text or "").strip()[:220]}
        if flag:
            flagged.append({"stem": i.get("stem"), "chat": i.get("chat"),
                            "size": i.get("size"), "flag": flag, "why": why,
                            "ocr": (text or "").strip()[:160]})
            all_flagged[i.get("stem")] = flagged[-1]
        if n % 100 == 0:
            log(f"  {n}/{len(todo)} ({len(flagged)} flagged so far, "
                f"{time.time()-t0:.0f}s)")
    try:
        import shutil as _sh
        _sh.rmtree(tmpdir)
    except OSError:
        pass

    # Final write (same merge/live-filter path as the mid-run checkpoints).
    cand = write_out()
    by_flag = {}
    for f in cand:
        by_flag[f["flag"]] = by_flag.get(f["flag"], 0) + 1
    log(f"spam scan DONE: {len(cand)} candidates {by_flag} — wrote {OUT}")
    sheet_items = [{"chat": f["chat"], "stem": f["stem"]} for f in cand[:96]]
    if sheet_items:
        build_sheet(sheet_items, SHEET)
    log("REVIEW REQUIRED: nothing was hidden or deleted. Eyeball the contact "
        "sheet, then approve with --approve " + str(OUT))


def approve(path: Path):
    """Hide the approved candidates + record them in the removal ledger.
    Hiding (never deleting) is the default here; deletion stays a user action
    in the Duplicates/Spam review UI."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from removal_ledger import record_many
    data = json.loads(path.read_text())
    cand = data.get("candidates") or []
    if not cand:
        log("no candidates to approve")
        return 1
    # group by chat so the hidden-ledger write mirrors per folder
    by_chat = {}
    for c in cand:
        by_chat.setdefault(c.get("chat") or "", []).append(c)
    HIDDEN = Path(os.environ.get("TG_HIDDEN_FILE", str(STATE / "hidden.json")))
    try:
        raw = json.loads(HIDDEN.read_text())
        hidden = set(raw.get("hidden") or [])
        keep = set(raw.get("keep") or [])
    except (OSError, ValueError):
        hidden, keep = set(), set()
    added = []
    for _chat, items in by_chat.items():
        for c in items:
            s = c.get("stem")
            if not s or s in keep:
                continue
            hidden.add(s)
            added.append(c)
    tmp = str(HIDDEN) + ".tmp"
    Path(tmp).write_text(json.dumps({"hidden": sorted(hidden),
                                     "keep": sorted(keep)}, separators=(",", ":")))
    os.replace(tmp, HIDDEN)
    record_many([{"stem": c["stem"], "chat": c.get("chat"), "size": c.get("size") or 0}
                 for c in added],
                action="dedup_hidden", reason="spam",
                detail=(added[0].get("why") if added else ""),
                by="spam_scan", exclude=True)
    log(f"approved {len(added)} spam candidates: hidden + recorded "
        f"(reason=spam); re-run the refresh to rebuild the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
