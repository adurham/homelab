#!/usr/bin/env python3
"""
Fleet-wide folder-duplicate audit for the media gallery.

WHY: the 5 folder merges done 2026-09-12 (Darcee-S->Darcee, SinsJupiter->
Jupiter, bynirva->byniirva, Viper->litenrevv, person_1->Lulu) all started from
the user manually spotting duplicates by eye. There are ~370 other folders
that were never systematically checked for the same issue. This script is
that systematic check — READ-ONLY, reports candidates for human review, never
merges/hides/deletes/moves anything itself. The actual merge, when the user
confirms a candidate, is POST /merge/<from>/<to> (see upload_service.py) —
already built and tested (tests/test_merge_redirect.py).

THREE independent signals, each catching a different real-world case:

  A. CHAT-ID OVERLAP (high confidence). Two folders whose item stems (or
     folder_meta.json's own chat_ids field) share a Telegram chat id are
     almost certainly the same source filed under two names — this is
     exactly the Darcee-S/Darcee and SinsJupiter/Jupiter pattern. Free to
     compute: chat ids are recoverable from stems already in the manifest
     (folder_redirect.extract_chat_ids, the same helper the real /merge
     endpoint uses) or from folder_meta.json's curated list.

  B. PERCEPTUAL-HASH CROSS-FOLDER OVERLAP (high/medium confidence). Catches
     the bynirva/byniirva case: two different scrape usernames (no shared
     chat id at all — scraper stems have no chat id, see extract_chat_ids'
     own docstring) that are actually the same real person, so their actual
     photos collide. Reuses dedup_scan.py's dHash cache (already computed
     and refreshed hourly by the live dedup pipeline — this script adds ZERO
     new hashing cost) and its proven LSH-banded find_duplicate_pairs
     (imported directly, not reimplemented, so it inherits the same
     lossless-at-HAMMING<=6 guarantee). A confirmed close item-pair whose two
     stems belong to different folders is evidence for THOSE folders being
     duplicates; tally per folder-pair and rank by overlap ratio against the
     smaller folder (so a stale PARTIAL scrape — a subset of a fuller one,
     like bynirva was of byniirva — still surfaces as a strong signal even
     though the ratio against the larger folder would look weak).

  C. NAME SIMILARITY (low confidence, manual-review-only). A pure string
     check for folders with NEITHER of the above signals — e.g. a
     near-identical typo'd scrape username with too little actual overlap
     to trip signal B (bynirva/byniirva would likely ALSO be caught here
     independently, since it's a one-character difference). This signal
     alone is not actionable; it exists to surface candidates a human should
     eyeball, matching how the user originally found some of the first 5
     pairs (Viper/litenrevv, person_1/Lulu) with no automatic evidence at
     all — this script can't replace that judgment, only narrow where to
     look.

Never touches folder_meta.json, never calls /merge, never deletes/hides/moves
a single file. Output is a JSON report (for tooling) plus a human-readable
text summary printed to stdout, both written locally — see OUT_JSON/OUT_TXT.

Usage:
    python3 folder_dupe_audit.py [--min-hash-overlap 0.3] [--min-name-ratio 0.82]

Env: RCLONE_CONFIG, TG_RCLONE_REMOTE (default gcrypt:), TG_FOLDER_META,
     DEDUP_HASH_CACHE (all default to the same paths dedup_scan.py/
     upload_service.py already use — see their own env docs).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import folder_redirect  # noqa: E402
from dedup_scan import (  # noqa: E402
    find_duplicate_pairs,
    load_hash_cache,
)

REMOTE = os.environ.get("TG_RCLONE_REMOTE", "gcrypt:")
RCLONE_CONF = os.environ.get("RCLONE_CONFIG", "")
GALLERY = REMOTE + "gallery"
FOLDER_META_FILE = Path(os.environ.get(
    "TG_FOLDER_META", "/var/lib/media-gallery/folder_meta.json"))
OUT_JSON = Path(os.environ.get(
    "FOLDER_DUPE_AUDIT_OUT", "/var/lib/media-gallery/folder_dupe_audit.json"))
OUT_TXT = OUT_JSON.with_suffix(".txt")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def rclone(*args):
    cmd = ["rclone"]
    if RCLONE_CONF:
        cmd += ["--config", RCLONE_CONF]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def load_folder_meta() -> dict:
    try:
        return json.loads(FOLDER_META_FILE.read_text())
    except (OSError, ValueError):
        return {}


def fetch_manifest() -> list:
    """Fresh copy, same pattern as dedup_scan.py — manifest.json is small
    (one file) so re-fetching every audit run is cheap and always current."""
    work = Path(tempfile.mkdtemp(prefix="fdaudit_"))
    mp = work / "manifest.json"
    r = rclone("copyto", f"{GALLERY}/manifest.json", str(mp))
    if r.returncode != 0:
        log("cannot fetch manifest:", r.stderr[:300])
        sys.exit(1)
    data = json.loads(mp.read_text())
    mp.unlink()
    return data


def build_folder_index(manifest: list, meta: dict):
    """Returns (folder -> set(stems), folder -> set(chat_ids), folder -> size_bytes_total).

    'chat' in each manifest item IS the on-disk folder name (see
    build_manifest.py's list_originals(): by-chat/<chat>/<leaf> — chat here
    is the folder, not a raw numeric id), so grouping by it directly gives
    folder membership with no extra resolution step.
    """
    folder_stems = defaultdict(set)
    folder_sizes = defaultdict(int)
    for item in manifest:
        folder = item.get("chat")
        if not folder:
            continue
        folder_stems[folder].add(item["stem"])
        folder_sizes[folder] += item.get("size") or 0

    folder_chat_ids = {}
    redirects = meta.get("redirects", {}) if isinstance(meta, dict) else {}
    already_merged_away = {
        k.split(":", 1)[1] for k in redirects
        if k.startswith("name:") or k.startswith("user:")
    }
    for folder, stems in folder_stems.items():
        ids = set(folder_redirect.extract_chat_ids(stems))
        entry = meta.get(folder) if isinstance(meta, dict) else None
        if isinstance(entry, dict):
            ids |= set(entry.get("chat_ids") or [])
        folder_chat_ids[folder] = ids

    return folder_stems, folder_chat_ids, folder_sizes, already_merged_away


def signal_chat_overlap(folder_chat_ids: dict, skip: set):
    """Folders (not already merged-away) sharing >=1 chat id."""
    by_chat = defaultdict(list)
    for folder, ids in folder_chat_ids.items():
        if folder in skip:
            continue
        for cid in ids:
            by_chat[cid].append(folder)
    pairs = {}
    for cid, folders in by_chat.items():
        if len(folders) < 2:
            continue
        for a, b in combinations(sorted(set(folders)), 2):
            key = tuple(sorted((a, b)))
            pairs.setdefault(key, set()).add(cid)
    return pairs  # {(folder_a, folder_b): {shared_chat_ids}}


def signal_hash_overlap(folder_stems: dict, skip: set, min_ratio: float, cache: dict = None):
    """Cross-folder perceptual-hash collisions via dedup_scan's own proven
    LSH-banded matcher — zero new hashing, just aggregation of its output by
    folder membership instead of by item union-find.

    `cache` injectable for testing (stem -> int hash); omitted => production
    dedup_scan.py hash cache (already computed/refreshed by the live
    ingest-time + hourly dedup pipeline)."""
    if cache is None:
        cache = load_hash_cache()
    stem_to_folder = {}
    for folder, stems in folder_stems.items():
        if folder in skip:
            continue
        for s in stems:
            stem_to_folder[s] = folder

    relevant_stems = [s for s in cache if s in stem_to_folder]
    if len(relevant_stems) < 2:
        return {}
    hash_list = [cache[s] for s in relevant_stems]

    overlap_counts = defaultdict(int)
    for a, b in find_duplicate_pairs(relevant_stems, hash_list):
        fa, fb = stem_to_folder[a], stem_to_folder[b]
        if fa == fb:
            continue
        key = tuple(sorted((fa, fb)))
        overlap_counts[key] += 1

    results = {}
    for (fa, fb), count in overlap_counts.items():
        smaller = min(len(folder_stems[fa]), len(folder_stems[fb]))
        ratio = count / smaller if smaller else 0
        if ratio >= min_ratio:
            results[(fa, fb)] = {"overlap_items": count, "ratio_vs_smaller": round(ratio, 3)}
    return results


def signal_name_similarity(folders: list, already_flagged: set, min_ratio: float):
    """Pure string similarity among folders with NEITHER signal above —
    manual-review-only bucket. Length-gated to keep this from being O(n^2)
    noise: only compares names within 40% length of each other."""
    results = {}
    names = sorted(folders)
    for a, b in combinations(names, 2):
        key = tuple(sorted((a, b)))
        if key in already_flagged:
            continue
        la, lb = len(a), len(b)
        if la == 0 or lb == 0:
            continue
        if abs(la - lb) / max(la, lb) > 0.4:
            continue
        ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
        if ratio >= min_ratio:
            results[key] = round(ratio, 3)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hash-overlap", type=float, default=0.3,
                     help="min overlap-items/smaller-folder-size ratio for signal B (default 0.3)")
    ap.add_argument("--min-name-ratio", type=float, default=0.82,
                     help="min difflib similarity ratio for signal C (default 0.82)")
    args = ap.parse_args()

    meta = load_folder_meta()
    manifest = fetch_manifest()
    log(f"manifest items: {len(manifest)}")

    folder_stems, folder_chat_ids, folder_sizes, skip = build_folder_index(manifest, meta)
    log(f"folders: {len(folder_stems)} total, {len(skip)} already merged-away (skipped)")

    chat_pairs = signal_chat_overlap(folder_chat_ids, skip)
    log(f"signal A (chat-id overlap): {len(chat_pairs)} candidate pair(s)")

    hash_pairs = signal_hash_overlap(folder_stems, skip, args.min_hash_overlap)
    log(f"signal B (perceptual-hash overlap, ratio>={args.min_hash_overlap}): "
        f"{len(hash_pairs)} candidate pair(s)")

    flagged = set(chat_pairs) | set(hash_pairs)
    live_folders = [f for f in folder_stems if f not in skip]
    name_pairs = signal_name_similarity(live_folders, flagged, args.min_name_ratio)
    log(f"signal C (name similarity, ratio>={args.min_name_ratio}, "
        f"no other evidence): {len(name_pairs)} candidate pair(s)")

    def folder_info(f):
        return {"items": len(folder_stems.get(f, [])),
                "bytes": folder_sizes.get(f, 0)}

    report = {"generated_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
               "folders_scanned": len(folder_stems),
               "folders_skipped_already_merged": sorted(skip),
               "candidates": []}

    all_pairs = set(chat_pairs) | set(hash_pairs) | set(name_pairs)
    for pair in sorted(all_pairs, key=lambda p: (
            "A" if p in chat_pairs else "B" if p in hash_pairs else "C", p)):
        a, b = pair
        evidence = {}
        if pair in chat_pairs:
            evidence["shared_chat_ids"] = sorted(chat_pairs[pair])
        if pair in hash_pairs:
            evidence["hash_overlap"] = hash_pairs[pair]
        if pair in name_pairs:
            evidence["name_similarity_ratio"] = name_pairs[pair]
        confidence = "high" if (pair in chat_pairs or pair in hash_pairs) else "low_manual_review_only"
        report["candidates"].append({
            "folder_a": a, "folder_b": b,
            "confidence": confidence,
            "evidence": evidence,
            "folder_a_info": folder_info(a),
            "folder_b_info": folder_info(b),
        })

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2))

    lines = [
        f"Folder duplicate audit — {report['generated_utc']}",
        f"Folders scanned: {report['folders_scanned']} "
        f"({len(skip)} already-merged skipped)",
        f"Candidates found: {len(report['candidates'])} "
        f"(A/chat-id: {len(chat_pairs)}, B/hash: {len(hash_pairs)}, "
        f"C/name-only: {len(name_pairs)})",
        "",
    ]
    for c in report["candidates"]:
        a_info, b_info = c["folder_a_info"], c["folder_b_info"]
        lines.append(
            f"[{c['confidence']}] {c['folder_a']} ({a_info['items']} items) "
            f"<-> {c['folder_b']} ({b_info['items']} items)")
        for k, v in c["evidence"].items():
            lines.append(f"    {k}: {v}")
    OUT_TXT.write_text("\n".join(lines) + "\n")

    log(f"report written: {OUT_JSON} / {OUT_TXT}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
