#!/usr/bin/env python3
"""Tests for arbitrarily nested KB folders.

A folder index may declare sub-folders in `entries` (root-index shape, `folder`
relative to the declaring index). The walk must reach any depth, compose folder-topic
inheritance down the whole chain, and fail loudly on a cycle or a KB-root escape
instead of recursing forever or silently dropping docs.

Run: python3 test_nested_folders.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"


def _build(d: Path) -> Path:
    """findings/{flat} → findings/recovery/{hazard} → findings/recovery/deep/{very-deep}."""
    kb = d / ".claude" / "knowledge"
    (kb / "findings" / "recovery" / "deep").mkdir(parents=True)
    (kb / "instrument").mkdir()

    (kb / "index.json").write_text(json.dumps({
        "description": "nested",
        "entries": {
            "findings": {"folder": "findings/", "description": "f", "topics": ["thresholds"]},
            "instrument": {"folder": "instrument/", "description": "i", "topics": ["simulator"]},
            "root-doc.md": {"description": "r", "topics": ["simulator"]},
        },
    }))
    (kb / "findings" / "index.json").write_text(json.dumps({
        "description": "f",
        "entries": {"recovery": {"folder": "recovery/", "description": "rec", "topics": ["recovery"]}},
        "files": {"flat-finding.md": {"description": "ff", "topics": ["hazard"]}},
    }))
    (kb / "findings" / "recovery" / "index.json").write_text(json.dumps({
        "description": "rec",
        "entries": {"deep": {"folder": "deep/", "description": "d", "topics": ["deep-thing"]}},
        "files": {"hazard-curve.md": {"description": "hc", "topics": ["hazard"]}},
    }))
    (kb / "findings" / "recovery" / "deep" / "index.json").write_text(json.dumps({
        "description": "d", "files": {"very-deep.md": {"description": "vd", "topics": ["spill"]}},
    }))
    (kb / "instrument" / "index.json").write_text(json.dumps({
        "description": "i", "files": {"spill.md": {"description": "s", "topics": ["spill"]}},
    }))
    for rel in ("root-doc.md", "findings/flat-finding.md", "findings/recovery/hazard-curve.md",
                "findings/recovery/deep/very-deep.md", "instrument/spill.md"):
        (kb / rel).write_text(f"# {rel}\n")
    (kb / "topics.json").write_text(json.dumps(
        ["thresholds", "simulator", "recovery", "hazard", "deep-thing", "spill"]))
    (kb / ".kbignore").write_text("inbox\n.kb\n")
    return kb


def _probe(kb: Path, body: str) -> str:
    code = textwrap.dedent(f"""
        import os, sys, json
        os.environ["KB_ROOT"] = {str(kb)!r}
        sys.path.insert(0, {str(SCRIPTS)!r})
        import kb_graph
    """) + textwrap.dedent(body)
    r = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True)
    return r.stdout + r.stderr


def test_inheritance_composes_down_the_chain():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        out = _probe(kb, """
            t = kb_graph._load_doc_topics()
            print(json.dumps({k: sorted(v) for k, v in t.items()}))
        """)
        got = json.loads(out.strip().splitlines()[-1])
        assert got["findings/recovery/hazard-curve.md"] == ["hazard", "recovery", "thresholds"], got
        assert got["findings/recovery/deep/very-deep.md"] == [
            "deep-thing", "recovery", "spill", "thresholds"], got
        assert got["root-doc.md"] == ["simulator"], got


def test_file_level_topics_ignore_inheritance():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        out = _probe(kb, """
            t = kb_graph._load_doc_topics(inherit=False)
            print(json.dumps({k: sorted(v) for k, v in t.items()}))
        """)
        got = json.loads(out.strip().splitlines()[-1])
        assert got["findings/recovery/deep/very-deep.md"] == ["spill"], got


def test_nested_doc_gets_edges_and_is_not_orphaned():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        out = _probe(kb, """
            print(kb_graph.check())
            print("EDGE:", "very-deep" in kb_graph.related("instrument/spill.md"))
        """)
        assert "OK — all 5 docs" in out, out
        assert "EDGE: True" in out, out


def test_membership_includes_every_ancestor_folder():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        out = _probe(kb, "print(json.dumps(kb_graph.folder_groups()))")
        g = json.loads(out.strip().splitlines()[-1])
        assert g["findings/"] == ["findings/flat-finding.md",
                                  "findings/recovery/deep/very-deep.md",
                                  "findings/recovery/hazard-curve.md"], g
        assert g["findings/recovery/deep/"] == ["findings/recovery/deep/very-deep.md"], g


def test_cycle_fails_loudly():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        idx = kb / "findings" / "recovery" / "deep" / "index.json"
        data = json.loads(idx.read_text())
        data["entries"] = {"back": {"folder": "../", "description": "cycle", "topics": []}}
        idx.write_text(json.dumps(data))
        out = _probe(kb, "kb_graph._load_doc_topics()")
        assert "KB index cycle" in out, out


def test_escape_above_kb_root_fails_loudly():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        data = json.loads((kb / "index.json").read_text())
        data["entries"]["out"] = {"folder": "../", "description": "escape", "topics": []}
        (kb / "index.json").write_text(json.dumps(data))
        out = _probe(kb, "kb_graph._load_doc_topics()")
        assert "escapes the KB root" in out, out


def test_doctor_sees_nested_dangling_folder_and_tag_repeat():
    with tempfile.TemporaryDirectory() as d:
        kb = _build(Path(d))
        idx = kb / "findings" / "recovery" / "index.json"
        data = json.loads(idx.read_text())
        data["entries"]["ghost"] = {"folder": "ghost/", "description": "missing", "topics": []}
        data["files"]["hazard-curve.md"]["topics"] = ["hazard", "recovery"]
        idx.write_text(json.dumps(data))
        out = subprocess.run([sys.executable, str(SCRIPTS / "kb-doctor.py"), str(kb)],
                             text=True, capture_output=True).stdout
        assert "findings/recovery/ghost/" in out, out
        assert "hazard-curve.md  repeats folder tag(s): recovery" in out, out


def test_flat_kb_unaffected():
    """A folder index with only `files` must behave exactly as before nesting existed."""
    with tempfile.TemporaryDirectory() as d:
        kb = Path(d) / ".claude" / "knowledge"
        (kb / "a").mkdir(parents=True)
        (kb / "index.json").write_text(json.dumps({
            "description": "flat",
            "entries": {"a": {"folder": "a/", "description": "a", "topics": ["cat"]},
                        "top.md": {"description": "t", "topics": ["x"]}},
        }))
        (kb / "a" / "index.json").write_text(json.dumps({
            "description": "a", "files": {"one.md": {"description": "o", "topics": ["x"]}}}))
        (kb / "top.md").write_text("# top\n")
        (kb / "a" / "one.md").write_text("# one\n")
        (kb / "topics.json").write_text(json.dumps(["cat", "x"]))
        (kb / ".kbignore").write_text("inbox\n.kb\n")
        out = _probe(kb, """
            print(json.dumps({k: sorted(v) for k, v in kb_graph._load_doc_topics().items()}))
            print(json.dumps(kb_graph.folder_groups()))
        """)
        lines = out.strip().splitlines()
        assert json.loads(lines[-2]) == {"top.md": ["x"], "a/one.md": ["cat", "x"]}, lines
        assert json.loads(lines[-1]) == {"a/": ["a/one.md"]}, lines


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
