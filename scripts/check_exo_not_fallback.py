#!/usr/bin/env python3
"""CI guard (owner directive, 2026-10-11): the exo-served model must NEVER be a fallback.

Scans the hermes_gateway role's config sources (Jinja templates, vars, defaults)
for the exo-served model or the exo provider appearing inside a FALLBACK context
(``fallback:`` / ``fallback_providers:`` sections, or inline on a fallback line),
and exits non-zero on any hit.

Allowed by design (not a fallback): model catalog entries, provider ``default:``
model pins, reasoning-effort maps, ``delegation.by_provider`` / ``web.by_provider``
routing keys, the dormant ``hermes_gateway_main_provider == 'exo'`` main branch,
and comments (comments are skipped entirely).

Run from the repo root:  python3 scripts/check_exo_not_fallback.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible" / "roles" / "hermes_gateway"
SCAN_DIRS = (ROLE / "templates", ROLE / "vars", ROLE / "defaults")
SUFFIXES = (".yml", ".yaml", ".j2")

EXO_MARKERS = (
    "dealignai/",  # the exo-served model id prefix
    "provider: exo",  # exo as a fallback provider (any model)
    "provider: custom:exo",
)
SECTION_RE = re.compile(r"^\s*(?:fallback_providers|fallback):\s*(?:#.*)?$")
INLINE_RE = re.compile(
    r"\bfallback\w*:[^\n]*(?:dealignai/|provider:\s*(?:custom:)?exo\b)", re.IGNORECASE
)


def scan(path: Path) -> list[str]:
    """Return hit strings for exo refs in fallback contexts in one file."""
    hits: list[str] = []
    in_fallback = False
    fallback_indent = -1
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("{%"):
            continue  # blank / comment / Jinja control line — not config content
        indent = len(line) - len(line.lstrip())
        if in_fallback and indent <= fallback_indent:
            in_fallback = False
        if SECTION_RE.match(line):
            in_fallback = True
            fallback_indent = indent
            continue
        if INLINE_RE.search(line):
            hits.append(f"{path}:{lineno}: inline fallback reference: {stripped}")
        elif in_fallback and any(marker in line for marker in EXO_MARKERS):
            hits.append(f"{path}:{lineno}: exo inside fallback section: {stripped}")
    return hits


def main() -> int:
    hits: list[str] = []
    scanned = 0
    for base in SCAN_DIRS:
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES:
                scanned += 1
                hits.extend(scan(path))
    if hits:
        print("FAIL: exo-served model found in a fallback role (owner directive 2026-10-11):")
        for h in hits:
            print(f"  {h}")
        print("The exo model must never be a fallback for anything. See vars/model_routing.yml.")
        return 1
    print(f"OK: no exo-served model in any fallback role ({scanned} files scanned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
