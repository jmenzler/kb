#!/usr/bin/env python3
"""E2E tests for kb-obsidian.py — the Obsidian view exporter.

Plain asserts + subprocess, no pytest. Builds a temp git repo + KB, runs the
exporter, and checks the generated vault. Behaviour-level only.

Run:  python3 test_obsidian_e2e.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"


def init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "-C", str(root), "init", "-q"])
    subprocess.check_call(["git", "-C", str(root), "config", "user.email", "t@t.t"])
    subprocess.check_call(["git", "-C", str(root), "config", "user.name", "t"])
    return root


def write_kb(repo: Path, *, index: dict, topics: list, docs: dict[str, str],
             kbignore: str = "graphify-out\ninbox\n.kb\n") -> Path:
    kb = repo / ".claude" / "knowledge"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "index.json").write_text(json.dumps(index, indent=2))
    (kb / "topics.json").write_text(json.dumps(topics))
    (kb / ".kbignore").write_text(kbignore)
    for rel, body in docs.items():
        p = kb / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return kb


def run(*args: str, kb: Path, repo: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["KB_ROOT"] = str(kb)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "kb-obsidian.py"), *args],
        cwd=str(repo), env=env, text=True, capture_output=True,
    )


def linked_kb(repo: Path) -> Path:
    # two docs sharing topic "x" → should link to each other; one excluded inbox doc.
    docs = {
        "a.md": "# A\nAbout a.\n",
        "b.md": "# B\nAbout b.\n",
        "inbox/draft.md": "# Draft\nstaged.\n",
    }
    # share TWO topics so the link survives the strong-edge filter (>= MIN_SHARED_TOPICS).
    index = {"description": "t", "entries": {
        "a.md": {"topics": ["x", "y"]}, "b.md": {"topics": ["x", "y"]}}}
    return write_kb(repo, index=index, topics=["x", "y"], docs=docs)


def view_dir(kb: Path) -> Path:
    # vault lives at repo root (kb = <repo>/.claude/knowledge), visible to Obsidian.
    return kb.parent.parent / "kb-vault"


# --------------------------------------------------------------------------- #

def test_view_built_with_docs():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = linked_kb(repo)
        r = run(kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        v = view_dir(kb)
        assert (v / "a.md").exists() and (v / "b.md").exists(), "docs not copied"


def test_topic_wikilinks_both_directions():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = linked_kb(repo)
        run(kb=kb, repo=repo)
        v = view_dir(kb)
        a = (v / "a.md").read_text()
        b = (v / "b.md").read_text()
        assert "## Related" in a, "no Related section"
        assert "[[b]]" in a, f"a does not link b:\n{a}"
        assert "[[a]]" in b, f"b does not link a:\n{b}"


def test_tags_injected():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = linked_kb(repo)
        run(kb=kb, repo=repo)
        a = (view_dir(kb) / "a.md").read_text()
        assert a.startswith("---"), "no frontmatter"
        assert "tags:" in a and "x" in a.split("---", 2)[1], f"tag missing:\n{a}"


def test_excludes_inbox():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = linked_kb(repo)
        run(kb=kb, repo=repo)
        assert not (view_dir(kb) / "inbox" / "draft.md").exists(), "excluded doc copied"


def test_preserves_obsidian_config_on_regen():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = linked_kb(repo)
        run(kb=kb, repo=repo)
        cfg = view_dir(kb) / ".obsidian"
        cfg.mkdir(exist_ok=True)
        (cfg / "app.json").write_text("{}")
        # stale generated doc that no longer exists in KB should be cleared...
        (view_dir(kb) / "ghost.md").write_text("old")
        run(kb=kb, repo=repo)
        assert (cfg / "app.json").exists(), ".obsidian config wiped on regen"
        assert not (view_dir(kb) / "ghost.md").exists(), "stale doc not cleared"


def grouped_kb(repo: Path) -> Path:
    # docs in two folders → two groups; folder grouping is path-based (no index needed).
    docs = {
        "alpha/one.md": "# One\n",
        "alpha/two.md": "# Two\n",
        "beta/three.md": "# Three\n",
    }
    index = {"description": "t", "entries": {}}
    return write_kb(repo, index=index, topics=[], docs=docs)


def test_folder_group_tags():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = grouped_kb(repo)
        run(kb=kb, repo=repo)
        v = view_dir(kb)
        one = (v / "alpha" / "one.md").read_text()
        assert "group/alpha" in one, f"no folder group tag:\n{one}"


def test_color_groups_config():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = grouped_kb(repo)
        run(kb=kb, repo=repo)
        cfg = json.loads((view_dir(kb) / ".obsidian" / "graph.json").read_text())
        queries = {g["query"] for g in cfg["colorGroups"]}
        assert "tag:#group/alpha" in queries, queries
        assert "tag:#group/beta" in queries, queries


def test_group_hub_notes_link_members():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = grouped_kb(repo)
        run(kb=kb, repo=repo)
        hub = (view_dir(kb) / "_group-alpha.md")
        assert hub.exists(), "no group hub note"
        text = hub.read_text()
        assert "[[one]]" in text and "[[two]]" in text, f"hub missing members:\n{text}"


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
