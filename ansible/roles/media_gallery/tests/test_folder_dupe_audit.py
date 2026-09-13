#!/usr/bin/env python3
"""Tests for folder_dupe_audit.py — no network, no rclone, no live host.

Run from the role dir:
    python3 tests/test_folder_dupe_audit.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE_DIR = os.path.dirname(HERE)
FILES_DIR = os.path.join(ROLE_DIR, "files")
sys.path.insert(0, FILES_DIR)

import folder_dupe_audit as fda  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


# ── signal A: chat-id overlap ────────────────────────────────────────────
def test_chat_overlap_basic():
    folder_chat_ids = {
        "Darcee-S": {"8494407735"},
        "Darcee": {"8494407735"},
        "Unrelated": {"111"},
    }
    pairs = fda.signal_chat_overlap(folder_chat_ids, skip=set())
    check("finds Darcee-S/Darcee via shared chat id",
          ("Darcee", "Darcee-S") in pairs)
    check("shared chat id recorded",
          pairs.get(("Darcee", "Darcee-S")) == {"8494407735"})
    check("no false positive for Unrelated",
          not any("Unrelated" in p for p in pairs))


def test_chat_overlap_respects_skip():
    folder_chat_ids = {"A": {"1"}, "B": {"1"}}
    pairs = fda.signal_chat_overlap(folder_chat_ids, skip={"A"})
    check("skip set excludes already-merged folders", pairs == {})


def test_chat_overlap_three_way():
    # three folders sharing one chat id -> 3 pairs (A,B) (A,C) (B,C)
    folder_chat_ids = {"A": {"9"}, "B": {"9"}, "C": {"9"}}
    pairs = fda.signal_chat_overlap(folder_chat_ids, skip=set())
    check("three-way chat overlap yields C(3,2)=3 pairs", len(pairs) == 3)


# ── signal B: perceptual hash overlap ────────────────────────────────────
def test_hash_overlap_catches_partial_scrape():
    # byniirva has 4 items; bynirva (stale partial scrape) has 2, both of
    # which are near-duplicates (hamming<=6) of two of byniirva's items.
    # ratio vs SMALLER folder (bynirva, 2 items) should be high even though
    # ratio vs byniirva (4 items) would look weak — this is the exact
    # real-world case from the docstring.
    folder_stems = {
        "byniirva": {"b1", "b2", "b3", "b4"},
        "bynirva": {"n1", "n2"},
        "Unrelated": {"u1"},
    }
    cache = {
        "b1": 0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
        "n1": 0b00000000_00000000_00000000_00000000_00000000_00000000_00000000_00000001,  # hamming 1 vs b1
        "b2": 0b11111111_00000000_00000000_00000000_00000000_00000000_00000000_00000000,
        "n2": 0b11111111_00000000_00000000_00000000_00000000_00000000_00000000_00000010,  # hamming 1 vs b2
        "b3": 0b00000000_11111111_00000000_00000000_00000000_00000000_00000000_00000000,
        "b4": 0b00000000_00000000_11111111_00000000_00000000_00000000_00000000_00000000,
        "u1": 0b10101010_10101010_10101010_10101010_10101010_10101010_10101010_10101010,
    }
    results = fda.signal_hash_overlap(folder_stems, skip=set(), min_ratio=0.5, cache=cache)
    key = ("byniirva", "bynirva")
    check("byniirva/bynirva flagged", key in results)
    if key in results:
        check("overlap_items counted both matches", results[key]["overlap_items"] == 2)
        check("ratio computed against SMALLER folder (2 items) = 1.0",
              results[key]["ratio_vs_smaller"] == 1.0)
    check("Unrelated not flagged against anything",
          not any("Unrelated" in p for p in results))


def test_hash_overlap_same_folder_pairs_ignored():
    # two items in the SAME folder colliding must never produce a
    # self-pair (fa == fb) in the output.
    folder_stems = {"A": {"x1", "x2"}}
    cache = {"x1": 0, "x2": 1}  # hamming 1, same folder
    results = fda.signal_hash_overlap(folder_stems, skip=set(), min_ratio=0.01, cache=cache)
    check("same-folder hash collisions produce no cross-folder pair", results == {})


def test_hash_overlap_below_threshold_excluded():
    # A real 64-bit hash and a genuinely far one (popcount(XOR) > HAMMING=6):
    # flip alternating bits for a large Hamming distance, not just a numeric
    # shift (shifting doesn't reliably increase POPCOUNT distance from 0).
    far_hash = int("1010" * 16, 2)  # 32 bits set -> hamming(0, far_hash) = 32
    folder_stems = {"A": {"a1"}, "B": {"b1"}}
    cache = {"a1": 0, "b1": far_hash}
    results = fda.signal_hash_overlap(folder_stems, skip=set(), min_ratio=0.5, cache=cache)
    check("hashes genuinely far apart (hamming 32 > HAMMING 6) produce no match",
          results == {})


# ── signal C: name similarity ─────────────────────────────────────────────
def test_name_similarity_catches_typo():
    folders = ["bynirva", "byniirva", "TotallyDifferentName"]
    results = fda.signal_name_similarity(folders, already_flagged=set(), min_ratio=0.82)
    # "byniirva" < "bynirva" alphabetically (5th char 'i' < 'r'), so the
    # sorted pair key is (byniirva, bynirva), not (bynirva, byniirva).
    check("near-identical names flagged", ("byniirva", "bynirva") in results)
    check("dissimilar name not flagged against either",
          not any("TotallyDifferentName" in p for p in results))


def test_name_similarity_skips_already_flagged():
    folders = ["bynirva", "byniirva"]
    already = {("byniirva", "bynirva")}  # correct sorted order — see above
    results = fda.signal_name_similarity(folders, already_flagged=already, min_ratio=0.5)
    check("already-flagged pair not duplicated into signal C", results == {})


def test_name_similarity_length_gate():
    # "Lulu" (4 chars) vs "lulu50bunny" (11 chars): diff/max = 7/11 = 0.636
    # > 0.4 gate -> must be excluded even though "lulu" is a substring.
    # This is the EXACT pair the user explicitly said NOT to merge last
    # session (kept both, they're unrelated) — regression guard.
    folders = ["Lulu", "lulu50bunny"]
    results = fda.signal_name_similarity(folders, already_flagged=set(), min_ratio=0.3)
    check("Lulu vs lulu50bunny excluded by length gate (explicit prior non-merge)",
          results == {})


# ── build_folder_index ────────────────────────────────────────────────────
def test_build_folder_index_basic():
    manifest = [
        {"stem": "8494407735_100", "chat": "Darcee", "size": 1000},
        {"stem": "up_123_abc", "chat": "DanE", "size": 2000},
    ]
    meta = {"redirects": {"name:Darcee-S": "Darcee", "user:Darcee-S": "Darcee"}}
    folder_stems, folder_chat_ids, folder_sizes, skip = fda.build_folder_index(manifest, meta)
    check("folder_stems grouped by chat/folder", folder_stems["Darcee"] == {"8494407735_100"})
    check("chat id extracted from numeric-prefixed stem",
          "8494407735" in folder_chat_ids["Darcee"])
    check("upload stem (up_) contributes no chat id",
          folder_chat_ids["DanE"] == set())
    check("already-merged-away folder name captured in skip",
          "Darcee-S" in skip)
    check("folder byte totals summed", folder_sizes["DanE"] == 2000)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
