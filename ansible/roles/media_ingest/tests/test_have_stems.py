#!/usr/bin/env python3
"""Plain-python tests for media_ingest's store_client.have_stems() chunking
(2026-10-08). The reconcile sweep pre-checks stems against the gallery's
POST /have so it stops re-downloading media the gallery already holds; a
post-downtime history replay can enumerate many stems in one sweep, so the
client must chunk requests rather than build one oversized body.

Run with:  python3 tests/test_have_stems.py   (from the role dir)
No pytest, no network: the module-level `requests` name is monkeypatched.
"""
import os
import sys
import traceback
from pathlib import Path

ROLE_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROLE_DIR / "files"

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


def _fresh_import():
    os.environ.setdefault("AUTHENTIK_TOKEN_URL", "http://token.invalid/")
    os.environ.setdefault("COLLECTOR_CLIENT_ID", "cid")
    os.environ.setdefault("COLLECTOR_CLIENT_SECRET", "csecret")
    os.environ.setdefault("GALLERY_BASE", "http://gallery.invalid")
    for m in ("store_client",):
        if m in sys.modules:
            del sys.modules[m]
    sys.path.insert(0, str(FILES_DIR))
    import store_client as sc
    return sc


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_chunks_large_batches_and_returns_only_present():
    sc = _fresh_import()
    calls = []

    class FakeRequests:
        def post(self, url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "stems": json["stems"]})
            # gallery semantics: echo back only stems it "has" (even digits)
            have = [s for s in json["stems"] if s.split("_")[-1].isdigit()
                    and int(s.split("_")[-1]) % 2 == 0]
            return _Resp({"have": have})

        # token fetch path is never reached (headers are built lazily via
        # _auth_headers -> _get_token), so stub it too
        def get(self, *a, **k):
            raise AssertionError("unexpected GET")

    sc.requests = FakeRequests()
    sc._token["value"] = "fake-token"
    sc._token["exp"] = 1e18

    stems = [f"10_{i}" for i in range(450)]
    got = sc.have_stems(stems)

    if len(calls) != 3:
        raise AssertionError(f"450 stems must chunk into 3 requests of 200, got {len(calls)}")
    if any(len(c["stems"]) > 200 for c in calls):
        raise AssertionError("no single request may exceed the 200-stem chunk size")
    if any(c["url"] != "http://gallery.invalid/ingest/have" for c in calls):
        raise AssertionError(f"wrong endpoint: {calls[0]['url']!r}")
    expected = {s for s in stems if int(s.split("_")[-1]) % 2 == 0}
    if got != expected:
        raise AssertionError(f"have-set mismatch: {len(got)} != {len(expected)}")


def test_all_chunks_union_without_loss():
    """The union of chunk answers must cover stems in EVERY chunk, not just
    the first — an off-by-one in the chunk loop would silently re-push a tail
    of already-held media."""
    sc = _fresh_import()
    seen_chunks = []

    class FakeRequests:
        def post(self, url, headers=None, json=None, timeout=None):
            seen_chunks.append(list(json["stems"]))
            return _Resp({"have": json["stems"]})  # say yes to everything

        def get(self, *a, **k):
            raise AssertionError("unexpected GET")

    sc.requests = FakeRequests()
    sc._token["value"] = "t"
    sc._token["exp"] = 1e18
    stems = [f"x_{i}" for i in range(201)]
    got = sc.have_stems(stems)
    if len(seen_chunks) != 2:
        raise AssertionError(f"201 stems must chunk into 2 requests, got {len(seen_chunks)}")
    if got != set(stems):
        raise AssertionError(f"union lost stems: missing {sorted(set(stems) - got)[:5]!r}")


if __name__ == "__main__":
    print("test_have_stems: running")
    check("chunks large batches; returns exactly the present stems",
          test_chunks_large_batches_and_returns_only_present)
    check("all chunk answers union without loss", test_all_chunks_union_without_loss)
    print(f"test_have_stems: ALL {PASS} TESTS PASSED")
    print("PASS")
