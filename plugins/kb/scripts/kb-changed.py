#!/usr/bin/env python3
"""Incremental-clean scoping: which KB docs changed since the last clean.

Uses a per-doc content-hash marker (JSON) at .claude/knowledge/.kb/last-clean — robust to
mtime churn, git checkout/stash/rebase, and touch-without-change. A doc is "changed" if
its content hash differs from the marker or it is new. No marker → "FULL".

  kb-changed.py [kb_root]          list KB-relative *.md changed since the marker, one
                                   per line. Prints "FULL" if no marker → full sweep.
  kb-changed.py [kb_root] --mark   snapshot current hashes (call at end of clean).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
_flags = {a for a in sys.argv[1:] if a.startswith("--")}
if _args:
    os.environ["KB_ROOT"] = str(Path(_args[0]).resolve())

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_graph  # noqa: E402

KB_ROOT = kb_graph._KB_ROOT
MARKER = KB_ROOT / ".kb" / "last-clean"


def _hashes() -> dict[str, str]:
    out: dict[str, str] = {}
    for md in KB_ROOT.rglob("*.md"):
        rel = str(md.relative_to(KB_ROOT))
        if kb_graph.is_excluded(rel):
            continue
        try:
            out[rel] = hashlib.sha1(md.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def main() -> int:
    if "--mark" in _flags:
        now = _hashes()
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(json.dumps(now))
        print(f"marked {MARKER} ({len(now)} docs)")
        return 0

    if not MARKER.exists():
        print("FULL")
        return 0
    try:
        prev = json.loads(MARKER.read_text())
    except (json.JSONDecodeError, OSError):
        print("FULL")
        return 0

    now = _hashes()
    changed = sorted(rel for rel, h in now.items() if prev.get(rel) != h)
    for c in changed:
        print(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
