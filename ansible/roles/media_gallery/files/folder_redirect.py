#!/usr/bin/env python3
"""Durable folder merge/redirect resolution for the media gallery.

Canonical source of the redirect logic. Runs on the gallery host (media_gallery
role), imported by upload_service.py (the merge endpoint + ingest-time resolve).
Embedded semantic copies live in the ingest roles (collector.py / reconcile.py
/ scraper_wrapper.py) because those hosts cannot import this module — keep them
in sync; roles/media_gallery/tests/test_merge_redirect.py asserts equality.
"""
import re


def resolve_redirect(redirects, key, max_hops=10):
    """Follow a redirect chain cycle-safely.

    redirects[key] -> redirects[value] -> redirects[value...], following each
    value literally as the next key, until a value is not itself a key (the
    final target) or a cycle/limit is hit. Returns None when `key` is not a
    redirect key. Cycle-safe: a cycle returns the value that re-enters it.
    """
    seen = set()
    cur = key
    for _ in range(max_hops):
        if cur not in redirects:
            return None
        if cur in seen:
            return cur  # cycle — the value pointing back into the loop
        seen.add(cur)
        cur = redirects[cur]
        if cur not in redirects:
            return cur  # final target (not itself a redirect key)
    return None


def resolve_folder(redirects, folder, chat_id=None):
    """Resolve a folder through the redirect map.

    Precedence: 'chat:<chat_id>' > 'name:<folder>' > 'user:<folder>', each via
    resolve_redirect. Returns the original folder when nothing matches.
    """
    if chat_id is not None:
        r = resolve_redirect(redirects, "chat:%s" % chat_id)
        if r is not None:
            return r
    r = resolve_redirect(redirects, "name:%s" % folder)
    if r is not None:
        return r
    r = resolve_redirect(redirects, "user:%s" % folder)
    if r is not None:
        return r
    return folder


def merge_redirects(redirects, from_folder, to_folder, chat_ids):
    """Register redirects for a merge: 'name:FROM'->to, 'user:FROM'->to, and
    'chat:<cid>'->to for each chat id. Rewrites any existing redirect whose
    VALUE == from_folder to to_folder (chain collapse). Returns the updated dict.
    """
    out = dict(redirects or {})
    out["name:%s" % from_folder] = to_folder
    out["user:%s" % from_folder] = to_folder
    for cid in chat_ids:
        out["chat:%s" % cid] = to_folder
    # chain collapse: anything currently redirecting TO the merged-away folder
    # now points at the merge target directly.
    for k, v in list(out.items()):
        if v == from_folder:
            out[k] = to_folder
    return out


def extract_chat_ids(stems):
    """Numeric prefixes of stems matching ^(\\d+)_. Telegram stems are
    CHATID_MSGID so this recovers the chat id. Scraper (USERNAME_WxH_HASH) and
    browser (up_TS_HEX) stems have no numeric prefix -> ignored."""
    out = []
    for s in stems or []:
        m = re.match(r"^(\d+)_", s)
        if m:
            out.append(m.group(1))
    return out
