#!/usr/bin/env python3
"""Tests for the removal audit ledger, the video-dedupe tiers, and the spam
classifier's decision logic.

Plain-python style (same as the rest of this role's tests): no pytest, prints
PASS/FAIL, exits non-zero on failure, and touches NO network / no real state
(everything runs against a temp dir with a stubbed rclone).

Run:  python3 tests/test_removal_and_spam.py   (from the role dir)
"""
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"
sys.path.insert(0, str(FILES_DIR))

PASS = 0


def check(name, fn):
    global PASS
    try:
        fn()
        PASS += 1
        print(f"  ok  {name}")
    except Exception:
        print(f"  FAIL {name}\n" + traceback.format_exc())
        sys.exit(1)


def _fresh(mod_name, td):
    os.environ["TG_STATE_DIR"] = str(td)
    os.environ["TG_DELETIONS_FILE"] = str(td / "deletions.json")
    os.environ["TG_EXCLUDE_FILE"] = str(td / "excluded.json")
    os.environ["TG_DELETIONS_LOCK"] = str(td / "deletions.lock")
    os.environ["TG_SERVE_DIR"] = str(td / "serve")
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    import importlib
    mod = importlib.import_module(mod_name)
    importlib.reload(mod)
    return mod


def test_ledger_records_reason_and_excludes():
    """The core requirement: every removal is recorded WITH a reason, and the
    stem lands in the exclusion ledger the collectors gate on."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        rl = _fresh("removal_ledger", td)
        # no rclone available -> mirror attempts must not break recording
        rl.record_removal("s1", "cA", action="deleted", reason="user_delete",
                          size=100, by="user")
        rl.record_many([{"stem": "s2", "chat": "cA", "size": 200},
                        {"stem": "s3", "chat": "cB", "size": 300}],
                       action="dedup_hidden", reason="duplicate",
                       detail="dup of keep1", by="dedup_scan")
        entries = rl.load_ledger()
        if len(entries) != 3:
            raise AssertionError(f"expected 3 entries, got {len(entries)}")
        reasons = {e["stem"]: e["reason"] for e in entries}
        if reasons != {"s1": "user_delete", "s2": "duplicate", "s3": "duplicate"}:
            raise AssertionError(f"wrong reasons: {reasons}")
        ex = set(json.loads((td / "excluded.json").read_text()))
        if ex != {"s1", "s2", "s3"}:
            raise AssertionError(f"expected all 3 excluded, got {ex}")
        summ = rl.summary()
        if summ["by_reason"].get("duplicate") != 2:
            raise AssertionError(f"summary wrong: {summ}")


def test_ledger_exclude_false_keeps_stem_capturable():
    """A REVIEW-ONLY record (spam candidate) must NOT exclude the stem — only
    a real removal blocks the collectors."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        rl = _fresh("removal_ledger", td)
        rl.record_removal("cand1", "cA", action="spam_review",
                          reason="spam_candidate", exclude=False)
        entries = rl.load_ledger()
        if len(entries) != 1:
            raise AssertionError(f"expected 1 entry, got {len(entries)}")
        exf = td / "excluded.json"
        if exf.exists():
            ex = json.loads(exf.read_text())
            if ex:
                raise AssertionError(f"review-only must not exclude, got {ex}")


def test_ledger_caps_growth():
    """The ledger must not grow without bound (MAX_ENTRIES trims oldest) --
    and trimmed records must ROLL INTO THE ARCHIVE, not vanish. (Regression:
    the 2026-10-01 bulk reclaim silently dropped the earliest audit records
    once it passed the 50k cap -- exactly what this ledger exists to track.)"""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        rl = _fresh("removal_ledger", td)
        rl.MAX_ENTRIES = 5
        for i in range(12):
            rl.record_removal(f"s{i}", "c", exclude=False)
        entries = rl.load_ledger()
        if len(entries) != 5:
            raise AssertionError(f"expected trim to 5, got {len(entries)}")
        stems = [e["stem"] for e in entries]
        if stems != ["s7", "s8", "s9", "s10", "s11"]:
            raise AssertionError(f"expected the NEWEST 5, got {stems}")
        # the 7 trimmed records must survive in the archive, in order
        import json as _j
        arch = _j.loads(rl.ARCHIVE.read_text())["entries"]
        arch_stems = [e["stem"] for e in arch]
        if arch_stems != [f"s{i}" for i in range(7)]:
            raise AssertionError(f"expected archived s0..s6, got {arch_stems}")
        # a second overflow appends rather than replaces (3 more adds -> 3
        # more trims at MAX=5: archive 7 -> 10, live stays at 5)
        for i in range(12, 15):
            rl.record_removal(f"s{i}", "c", exclude=False)
        arch2 = _j.loads(rl.ARCHIVE.read_text())["entries"]
        if len(arch2) != 10:
            raise AssertionError(f"expected 10 archived after 2nd overflow, got {len(arch2)}")
        live2 = rl.load_ledger()
        if [e["stem"] for e in live2] != ["s10", "s11", "s12", "s13", "s14"]:
            raise AssertionError(f"live after 2nd overflow: {[e['stem'] for e in live2]}")


def test_video_upstream_id_tier_a():
    """Same embedded upstream post-id + same byte size = a duplicate group
    WITHOUT reading any bytes (Tier A)."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        dv = _fresh("dedup_videos", td)
        items = [
            {"stem": "userA_0hfs2uhp229as7zmuy8mr_source", "chat": "userA",
             "type": "video", "size": 900, "file": "by-chat/userA/x.mp4",
             "date": "2026-01-02"},
            {"stem": "userB_0hfs2uhp229as7zmuy8mr_source", "chat": "userB",
             "type": "video", "size": 900, "file": "by-chat/userB/y.mp4",
             "date": "2026-01-01"},
            # different id, same size -> NOT Tier A
            {"stem": "userC_0izn6rkkz0qcxydav4ww_source", "chat": "userC",
             "type": "video", "size": 900, "file": "by-chat/userC/z.mp4",
             "date": "2026-01-03"},
        ]
        groups = dv.find_video_duplicates(items, max_verify=0)  # Tier A only
        if len(groups) != 1 or len(groups[0]) != 2:
            raise AssertionError(f"expected one 2-member group, got {groups}")
        stems = {m["stem"] for m in groups[0]}
        if "userC_0izn6rkkz0qcxydav4ww_source" in stems:
            raise AssertionError("different upstream id must not join the group")
        shaped = dv.as_dedup_groups(groups)
        if shaped[0][0].get("kind") != "video":
            raise AssertionError("groups must be tagged kind=video")


def test_video_id_extraction_ignores_short_tokens():
    """Only long base36-ish tokens are upstream ids; short name parts aren't."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        dv = _fresh("dedup_videos", td)
        if dv._upstream_id("userA_0hfs2uhp229as7zmuy8mr_source") != "0hfs2uhp229as7zmuy8mr":
            raise AssertionError("failed to extract the real id")
        if dv._upstream_id("some_name_123_456") is not None:
            raise AssertionError("short numeric parts must not be ids")
        if dv._upstream_id("up_1789833659124_391d1ebb") is not None:
            raise AssertionError("browser-upload stems have no upstream id")


def test_video_groups_survive_hiding():
    """REGRESSION (2026-10-01): group detection must NOT filter out
    already-hidden members. The hide ledger is rebuilt from these groups every
    run; if a hidden member were excluded, a 2-member group would disintegrate
    after its first hide and the loser would be UNHIDDEN on the next scan
    (observed as 'duplicates came back after an hour')."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        dv = _fresh("dedup_videos", td)
        mk = lambda stem, chat, hidden: {  # noqa: E731
            "stem": stem, "chat": chat, "type": "video", "size": 500,
            "file": f"by-chat/{chat}/x.mp4", "date": "2026-01-01",
            "hidden": hidden}
        # same upstream id; the loser is ALREADY hidden from a previous run
        items = [
            mk("userA_0hfs2uhp229as7zmuy8mr_source", "userA", False),
            mk("userB_0hfs2uhp229as7zmuy8mr_source", "userB", True),
        ]
        groups = dv.find_video_duplicates(items, max_verify=0)
        if len(groups) != 1 or len(groups[0]) != 2:
            raise AssertionError(
                f"hidden member must stay in the group, got {groups}")


def test_spam_classifier_promo_and_ui():
    """The classifier's decision rules (no OCR needed — text is passed in)."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        ss = _fresh("spam_scan", td)
        # a real promo watermark caught live
        img = {"stem": "example_539x699_abc", "chat": "example",
               "size": 20000, "type": "image"}
        flag, why = ss.classify(img, "example.com/examplehandle", 1)
        if flag != "promo_text":
            raise AssertionError(f"expected promo_text, got {(flag, why)}")
        # a UI screenshot (several chrome words, small file)
        flag2, _ = ss.classify(img, "Skip Follow Message Subscribe", 4)
        if flag2 not in ("ui_screenshot", "promo_text"):
            raise AssertionError(f"expected a UI/promo flag, got {flag2}")
        # a normal photo's stray caption must NOT be flagged
        flag3, why3 = ss.classify(
            {"stem": "acct_g_123_456", "chat": "acct_g", "size": 500000, "type": "image"},
            "me on the beach last summer", 6)
        if flag3 is not None:
            raise AssertionError(f"normal photo flagged as {flag3}: {why3}")
        # profile art is its own class (weak flag, bulk-reviewable)
        flag4, _ = ss.classify(
            {"stem": "someone_avatar_2026_01_01", "chat": "someone",
             "size": 50000, "type": "image"}, "", 0)
        if flag4 != "profile_art":
            raise AssertionError(f"expected profile_art, got {flag4}")


def test_spam_approve_never_deletes():
    """Approval hides + records (reason=spam) — it must NEVER delete files."""
    with tempfile.TemporaryDirectory() as d:
        td = Path(d)
        ss = _fresh("spam_scan", td)
        rl = _fresh("removal_ledger", td)
        ss.STATE = td
        ss.OUT = td / "spam_candidates.json"
        cand = {"candidates": [
            {"stem": "bad1", "chat": "cA", "size": 111, "flag": "promo_text",
             "why": "OCR promo text: example.com"},
        ]}
        p = td / "spam_candidates.json"
        p.write_text(json.dumps(cand))
        os.environ["TG_HIDDEN_FILE"] = str(td / "hidden.json")
        ss.approve(p)
        hid = json.loads((td / "hidden.json").read_text())
        if "bad1" not in hid["hidden"]:
            raise AssertionError("approve must add the stem to hidden.json")
        entries = rl.load_ledger()
        if not entries or entries[-1]["reason"] != "spam":
            raise AssertionError(f"expected a reason=spam ledger entry, got {entries}")
        if entries[-1]["action"] != "dedup_hidden":
            raise AssertionError("approve must HIDE (dedup_hidden), never delete")


def main():
    print("test_removal_and_spam: running")
    check("ledger records reason + excludes stems", test_ledger_records_reason_and_excludes)
    check("review-only record does not exclude", test_ledger_exclude_false_keeps_stem_capturable)
    check("ledger caps growth (keeps newest)", test_ledger_caps_growth)
    check("video Tier A groups by upstream id", test_video_upstream_id_tier_a)
    check("upstream id extraction shape", test_video_id_extraction_ignores_short_tokens)
    check("video groups survive hiding (stability regression)",
          test_video_groups_survive_hiding)
    check("spam classifier promo/ui/normal/profile", test_spam_classifier_promo_and_ui)
    check("spam approve hides+records, never deletes", test_spam_approve_never_deletes)
    print(f"test_removal_and_spam: ALL {PASS} TESTS PASSED")
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
