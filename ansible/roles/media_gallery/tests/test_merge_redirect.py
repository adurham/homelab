#!/usr/bin/env python3
"""Tests for the durable folder-merge/redirect mechanism.

Run from the role dir:
    python3 tests/test_merge_redirect.py

No network, no rclone — all filesystem/remote side effects go through injected
callbacks. Covers the canonical module (folder_redirect.py), the merge_folder()
core wired into upload_service.py's /merge endpoint, and asserts the resolve
logic copied into the ingest roles (collector.py / reconcile.py /
scraper_wrapper.py) is semantically identical to the canonical source.
"""
import ast
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROLE_DIR = os.path.dirname(HERE)                       # roles/media_gallery
FILES_DIR = os.path.join(ROLE_DIR, "files")
ROLES_DIR = os.path.dirname(ROLE_DIR)                  # roles/ (parent of all roles)

# upload_service.py creates PENDING_ROOT under UPLOAD_STAGING on import — point
# it at a real temp dir so the import is clean and side-effect-free here.
_STAGING = tempfile.mkdtemp(prefix="fr_test_staging_")
os.environ.setdefault("UPLOAD_STAGING", _STAGING)
os.environ.setdefault("TG_FOLDER_META", os.path.join(_STAGING, "folder_meta.json"))

sys.path.insert(0, FILES_DIR)

import folder_redirect as fr  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────
def _func_source(path, names):
    """Extract the source of the named top-level function defs from `path`."""
    tree = ast.parse(open(path).read())
    parts = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            parts.append(ast.get_source_segment(open(path).read(), node))
            assert parts[-1]
    return "\n\n".join(parts), sorted(names)


def _exec_resolve_copies(path):
    """Exec the resolve_redirect/resolve_folder defs from `path` into a fresh
    namespace and return that namespace (for semantic-equality comparison)."""
    src, _ = _func_source(path, ("resolve_redirect", "resolve_folder"))
    ns = {}
    exec(src, ns)
    return ns


def _assert_semantically_identical(path):
    ns = _exec_resolve_copies(path)
    redirects = {
        "chat:111": "FolderB",
        "name:OldName": "NewName",
        "user:OldUser": "NewUser",
        "chat:222": "chat:333",
        "chat:333": "Final",
    }
    fixtures = [
        ("FolderA", None),
        ("OldName", None),
        ("OldName", "111"),          # chat redirect wins
        ("whatever", "222"),          # chat chain
        ("whatever", "333"),
        ("OldUser", None),           # user redirect
        ("FolderA", "111"),           # chat beats name
        ("NoAlias", None),            # passthrough
        ("NoAlias", "999"),           # unknown chat -> passthrough
    ]
    for folder, cid in fixtures:
        a = fr.resolve_folder(redirects, folder, cid)
        b = ns["resolve_folder"](redirects, folder, cid)
        assert a == b, f"{path}: mismatched resolve_folder({folder!r}, {cid!r}) {a} != {b}"
    # also compare resolve_redirect directly on chains/cycles
    for key in ("chat:222", "chat:333", "name:OldName", "user:OldUser", "missing"):
        assert fr.resolve_redirect(redirects, key) == ns["resolve_redirect"](redirects, key), path


# ── canonical module tests ────────────────────────────────────────────────
def test_resolve_redirect():
    assert fr.resolve_redirect({"A": "B"}, "A") == "B"          # direct
    assert fr.resolve_redirect({"A": "B", "B": "C"}, "A") == "C"  # chain
    assert fr.resolve_redirect({"A": "B", "B": "A"}, "A") in ("A", "B")  # cycle safe
    assert fr.resolve_redirect({"A": "B"}, "Z") is None        # missing key
    assert fr.resolve_redirect({}, "A") is None


def test_resolve_folder():
    r = {"chat:111": "FolderB", "name:OldName": "NewName", "user:OldUser": "NewUser"}
    assert fr.resolve_folder(r, "whatever,", "111") == "FolderB"     # chat precedence
    assert fr.resolve_folder(r, "OldName", None) == "NewName"        # name fallback
    assert fr.resolve_folder(r, "OldUser", None) == "NewUser"        # user fallback
    assert fr.resolve_folder(r, "NoAlias", None) == "NoAlias"        # passthrough
    assert fr.resolve_folder({}, "A", "1") == "A"


def test_merge_redirects():
    r = {}
    out = fr.merge_redirects(r, "OLD", "NEW", ["111", "222"])
    assert out["name:OLD"] == "NEW"
    assert out["user:OLD"] == "NEW"
    assert out["chat:111"] == "NEW"
    assert out["chat:222"] == "NEW"
    assert "OLD" not in out  # no un-namespaced keys
    # chain collapse: an existing redirect pointing at OLD gets rewritten
    r2 = {"chat:999": "OLD", "chat:777": "ZZ", "name:keep": "K"}
    out2 = fr.merge_redirects(r2, "OLD", "NEW", ["111"])
    assert out2["chat:999"] == "NEW"   # value OLD -> NEW
    assert out2["chat:777"] == "ZZ"     # unrelated preserved
    assert out2["name:keep"] == "K"     # unrelated preserved
    # source dict not mutated
    assert r2["chat:999"] == "OLD"


def test_extract_chat_ids():
    assert fr.extract_chat_ids(["123_456", "999_1"]) == ["123", "999"]
    assert fr.extract_chat_ids(["someuser_1200x800_aabbcc"]) == []   # scraper: no ^digits
    assert fr.extract_chat_ids(["up_1600000000000_abcd1234"]) == []  # browser upload
    assert fr.extract_chat_ids([]) == []
    assert fr.extract_chat_ids(None) == []


# ── merge_folder (upload_service /merge core) ────────────────────────────
def test_merge_folder_moves_and_dedupes():
    import upload_service as u
    fs = {}  # folder -> {stem: content} (leaf = stem + .jpg)

    def list_fn(folder):
        return ["%s.jpg" % s for s in fs.get(folder, {})]

    def move_fn(f, t, leaf):
        stem = os.path.splitext(leaf)[0]
        fs.setdefault(t, {})[stem] = fs.get(f, {}).pop(stem)

    def delete_fn(f, leaf):
        fs.get(f, {}).pop(os.path.splitext(leaf)[0], None)

    def purge_fn(folder):
        fs.pop(folder, None)

    fs["FromF"] = {"aaa": "x", "bbb": "y", "101_1": "t"}     # 101_1 is a telegram stem
    fs["ToF"] = {"bbb": "y"}                                   # bbb is a dupe
    meta = {
        "FromF": {"cover": "101_1", "chat_ids": []},
        "ToF": {"cover": "keepcover", "chat_ids": ["555"]},
    }
    new_meta, moved, dupes, cids = u.merge_folder(
        meta, "FromF", "ToF", list_fn, move_fn, delete_fn, purge_fn)
    # moved aaa + 101_1 (bbb already in to -> deleted), originals purged
    assert moved == 2, moved
    assert dupes == 1, dupes
    assert sorted(fs["ToF"]) == ["101_1", "aaa", "bbb"]
    assert "FromF" not in fs
    # meta: from entry removed, to keeps cover, chat_ids merged + deduped
    assert "FromF" not in new_meta
    assert new_meta["ToF"]["cover"] == "keepcover"
    assert new_meta["ToF"]["chat_ids"] == ["101", "555"]   # 101 from telegram stem + cover
    # redirects registered: chat:101 already; name/user for FromF
    rd = new_meta["redirects"]
    assert rd["chat:101"] == "ToF"
    assert rd["name:FromF"] == "ToF"
    assert rd["user:FromF"] == "ToF"
    # original meta untouched (copy semantics)
    assert "FromF" in meta


def test_merge_folder_idempotent_when_absent():
    import upload_service as u
    fs = {"ToF": {"x": "1"}}

    def list_fn(f):
        return ["%s.jpg" % s for s in fs.get(f, {})]

    def move_fn(f, t, leaf):
        stem = os.path.splitext(leaf)[0]
        fs.setdefault(t, {})[stem] = fs.get(f, {}).pop(stem)

    def delete_fn(f, leaf): pass

    def purge_fn(f): fs.pop(f, None)

    # second run: FromF is already gone (only redirects/chat_ids bookkeeping)
    meta = {
        "ToF": {"chat_ids": ["111"]},
        "redirects": {"chat:101": "ToF", "name:FromF": "ToF", "user:FromF": "ToF"},
    }
    new_meta, moved, dupes, cids = u.merge_folder(
        meta, "FromF", "ToF", list_fn, move_fn, delete_fn, purge_fn)
    assert moved == 0 and dupes == 0
    # from is absent, so no new chat_ids are extracted — survivor keeps its own
    assert new_meta["ToF"]["chat_ids"] == ["111"]  # re-merge is idempotent (dedupe)
    assert new_meta["redirects"]["chat:101"] == "ToF"
    assert "FromF" not in new_meta
    assert fs == {"ToF": {"x": "1"}}  # nothing moved


# ── semantic-identity of copied resolve logic in the ingest roles ─────────
def test_ingest_copies_semantically_identical():
    for rel in (
        "media_ingest/files/collector.py",
        "media_ingest/files/reconcile.py",
        "media_ingest_02/files/scraper_wrapper.py",
    ):
        _assert_semantically_identical(os.path.join(ROLES_DIR, rel))
    print("copies OK: collector.py, reconcile.py, scraper_wrapper.py")


def main():
    tests = [name for name in sorted(globals()) if name.startswith("test_")]
    failed = []
    for name in tests:
        try:
            globals()[name]()
            print("ok    %s" % name)
        except AssertionError as e:
            print("FAIL  %s: %s" % (name, e))
            failed.append(name)
    print("=" * 40)
    if failed:
        print("%d of %d tests FAILED: %s" % (len(failed), len(tests), ", ".join(failed)))
        sys.exit(1)
    print("ALL %d TESTS PASSED" % len(tests))


if __name__ == "__main__":
    main()
