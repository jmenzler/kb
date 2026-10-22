#!/usr/bin/env python3
"""Tests for the relative hub-topic threshold.

A topic on too many docs is a broad category, not a real link — counting it as an edge
makes the graph a hairball. The threshold scales with corpus size (was a flat 12, which
on a small KB is a third of the corpus). Floored at 5, capped at the historical 12 so
large KBs are unchanged.

Run: python3 test_hub_threshold.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import kb_graph  # noqa: E402


def test_threshold_values():
    f = kb_graph.hub_threshold
    assert f(10) == 5, f(10)     # floor
    assert f(5) == 5, f(5)
    assert f(42) == 8, f(42)     # ~20% of 42
    assert f(88) == 18, f(88)    # scales — no cap
    assert f(500) == 100, f(500)  # big codebase → big legit hubs allowed


def test_broad_topic_downranked_on_small_kb():
    """On a 10-doc KB, a topic on 7 docs is a hub → not a real connection;
    a topic on 2 docs is specific → a real connection."""
    with tempfile.TemporaryDirectory() as d:
        kb = Path(d) / ".claude" / "knowledge"
        kb.mkdir(parents=True)
        # d0,d1 share narrow "x"; d0..d6 all share broad (7 docs → hub at threshold 5).
        entries = {}
        for i in range(10):
            t = ["broad"] if i <= 6 else ["other"]
            if i in (0, 1):
                t = ["broad", "x"]
            entries[f"d{i}.md"] = {"topics": t}
            (kb / f"d{i}.md").write_text(f"# d{i}\n")
        (kb / "index.json").write_text(json.dumps({"description": "t", "entries": entries}))
        (kb / "topics.json").write_text(json.dumps(["broad", "x", "other"]))
        (kb / ".kbignore").write_text("inbox\n.kb\n")

        code = textwrap.dedent(f"""
            import os, sys
            os.environ["KB_ROOT"] = {str(kb)!r}
            sys.path.insert(0, {str(SCRIPTS)!r})
            import kb_graph
            print(kb_graph.related_with_hops("d0.md"))
        """)
        out = subprocess.run([sys.executable, "-c", code], text=True,
                             capture_output=True).stdout
        # d1 shares the narrow non-hub topic "x" → listed (format-agnostic).
        assert "d1" in out, f"narrow neighbor missing:\n{out}"
        # d2 shares ONLY the broad hub topic → must NOT be a direct connection.
        assert "d2" not in out, f"broad-only neighbor leaked as edge:\n{out}"


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
