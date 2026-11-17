#!/usr/bin/env python3
"""Pick a folder's cover image — one rule, used by build_manifest.

The owner can pin any item as a folder's cover (SPA "Set as folder cover" ->
POST /setcover -> folder_meta.json). That pin is user intent, not derived data,
so it must survive every manifest rebuild; before this module the rebuild picked
a cover from a heuristic and never looked at folder_meta, which is why a pinned
cover "kept getting lost" — it was correct in the SPA's own copy for a few
minutes and then overwritten by the next publish.

Rules, in order:
  1. the pinned item, when it exists and has a RENDERABLE thumbnail;
  2. otherwise the first IMAGE with a cached thumbnail (a video's poster is
     often absent -> a 404 and a permanently blank card);
  3. otherwise the first image;
  4. otherwise the newest item (old behaviour).
A pin whose thumbnail is not renderable is deliberately ignored rather than
honoured: a blank card is worse than the wrong picture, and the pin stays in
folder_meta so it comes back the moment its thumb exists.
"""

from pathlib import Path


def thumb_cached(thumb_path, cache_dir):
    """True when a thumb path ('thumb/<folder>/<file>.jpg') is on the tmpfs cache.

    Kept here (not in build_manifest) so the cover rule and its "can this even
    render?" test live together and can be unit-tested without telethon.
    """
    th = thumb_path or ""
    if not isinstance(th, str) or not th.startswith("thumb/"):
        return False
    try:
        return (Path(cache_dir) / th[len("thumb/"):]).stat().st_size > 0
    except OSError:
        return False


def pick_cover(items, pinned_stem="", has_thumb=None):
    """Return the thumb path for a folder's cover.

    items: date-desc list of {stem, type, thumb}; pinned_stem: the owner's pin
    ("" when none); has_thumb(thumb_path) -> bool (thumbnail readable right now).
    """
    if has_thumb is None:
        def _no_thumb(_p):
            return False
        has_thumb = _no_thumb

    def thumb_of(it):
        return it.get("thumb")

    if pinned_stem:
        for it in items:
            if it.get("stem") == pinned_stem:
                if it.get("type") == "image" or has_thumb(thumb_of(it)):
                    return thumb_of(it)
                break
    first_image = None
    for it in items:
        if it.get("type") != "image":
            continue
        if has_thumb(thumb_of(it)):
            return thumb_of(it)
        if first_image is None:
            first_image = thumb_of(it)
    if first_image:
        return first_image
    return thumb_of(items[0]) if items else None
