#!/usr/bin/env python3
"""Unit tests for cover_choice.pick_cover (pure; no guest, no thumbnails)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cover_choice import pick_cover  # noqa: E402

fails = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (("  " + str(extra)) if extra else ""))
    if not cond:
        fails.append(label)


def it(stem, type_="image", thumb=None):
    return {"stem": stem, "type": type_, "thumb": thumb or f"thumb/f/{stem}.jpg"}


# newest-first list, like the manifest gives us
items = [it("new_video", "video"), it("img_a"), it("img_b"), it("old_video", "video")]

cached = {"thumb/f/img_b.jpg"}          # only img_b's thumb is on the tmpfs
has = lambda p: p in cached             # noqa: E731

# 1. no pin -> first IMAGE with a cached thumb, even though the newest is a video
check("no pin prefers a cached image", pick_cover(items, "", has) == "thumb/f/img_b.jpg")

# 2. a pin on a cached image wins over the heuristic's own pick
cached3 = {"thumb/f/img_a.jpg", "thumb/f/img_b.jpg"}   # heuristic would take img_a
check("pin on a cached image beats the heuristic",
      pick_cover(items, "img_b", lambda p: p in cached3) == "thumb/f/img_b.jpg")
check("pin on an uncached image wins (images always render)",
      pick_cover(items, "img_a", has) == "thumb/f/img_a.jpg")

# 3. a pin on a video with no poster is ignored (blank card is worse)
check("pin on a video without a poster falls back",
      pick_cover(items, "new_video", has) == "thumb/f/img_b.jpg")
cached2 = set(cached) | {"thumb/f/new_video.jpg"}
check("pin on a video WITH a poster is honoured",
      pick_cover(items, "new_video", lambda p: p in cached2) == "thumb/f/new_video.jpg")

# 4. a pin naming a deleted item is ignored
check("stale pin falls back", pick_cover(items, "gone", has) == "thumb/f/img_b.jpg")

# 5. no cached thumb at all -> first image
check("nothing cached -> first image",
      pick_cover(items, "", lambda p: False) == "thumb/f/img_a.jpg")

# 6. no images at all -> newest item (old behaviour)
vids = [it("v1", "video"), it("v2", "video")]
check("videos only -> newest", pick_cover(vids, "", lambda p: False) == "thumb/f/v1.jpg")

# 7. empty folder
check("empty -> None", pick_cover([], "", has) is None)

# 8. thumb_cached: path-shaped input, nothing weird on the filesystem
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from cover_choice import thumb_cached  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    Path(td, "f").mkdir()
    Path(td, "f", "a.jpg").write_bytes(b"x")
    check("cached when the file exists", thumb_cached("thumb/f/a.jpg", td) is True)
    check("miss when absent", thumb_cached("thumb/f/nope.jpg", td) is False)
    check("non-thumb path is never cached", thumb_cached("/etc/passwd", td) is False)
    check("None/empty is not cached", thumb_cached(None, td) is False
          and thumb_cached("", td) is False)

print("\n%d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
