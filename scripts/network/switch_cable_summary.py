#!/usr/bin/env python3
"""switch_cable_summary.py -- print a compact human summary of the switch's
cable-tester results page (/tmp/swcable/results.html).

The GS108Ev4 renders the test outcome as a per-port list; this reduces it to
plain text (port, pair statuses, length) so the result can be read without a
browser. Defensive by design: if the page shape differs from expectation it
prints the visible text verbatim rather than guessing.
"""
import html
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/swcable/results.html"
try:
    raw = open(path, errors="replace").read()
except OSError as e:
    print(f"no results page at {path} ({e})")
    raise SystemExit(1)

print(f"results page: {len(raw)} bytes")
# hidden inputs often carry the parsed state (counters style), so show them too
for m in re.finditer(r"<input[^>]*>", raw, re.I):
    tag = re.sub(r"\s+", " ", m.group(0))
    if "hidden" in tag.lower() or "value" in tag.lower():
        print("  input:", tag[:160])

txt = re.sub(r"<script.*?</script>", " ", raw, flags=re.S)
txt = html.unescape(re.sub(r"<[^>]+>", "|", txt))
txt = re.sub(r"[|\s]*\|[|\s]*", " | ", txt).strip(" |")
print("\nvisible text:")
print("  " + re.sub(r"\s{2,}", " ", txt)[:1800])
