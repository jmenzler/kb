#!/usr/bin/env python3
"""E2E integration tests for the self-auditing KB combo.

No pytest dependency — plain asserts + a tiny runner. Each test builds a real
temp git repo + KB + a hand-crafted .kb/ast-graph.json (schema matches kb-ast.py
output), then shells out to the actual scripts. Behaviour-level assertions only.

Run:  python3 test_self_audit_e2e.py
Exit 0 = all pass.
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


# --------------------------------------------------------------------------- #
# Fixture helpers
# --------------------------------------------------------------------------- #

def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, env=env, stderr=subprocess.STDOUT
    )


def init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    return root


def write_kb(repo: Path, *, index: dict, topics: list, docs: dict[str, str],
             graph: dict | None = None, kbignore: str = "graphify-out\ninbox\n.kb\n") -> Path:
    kb = repo / ".claude" / "knowledge"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "index.json").write_text(json.dumps(index, indent=2))
    (kb / "topics.json").write_text(json.dumps(topics))
    (kb / ".kbignore").write_text(kbignore)
    for rel, body in docs.items():
        p = kb / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    if graph is not None:
        gdir = kb / ".kb"
        gdir.mkdir(exist_ok=True)
        (gdir / "ast-graph.json").write_text(json.dumps(graph))
    return kb


def node(nid: str, label: str, source_file: str, line: int, ftype: str = "code") -> dict:
    return {"id": nid, "label": label, "file_type": ftype,
            "source_file": source_file, "source_location": f"L{line}"}


def graph(nodes: list[dict], edges: list[tuple[str, str, str]]) -> dict:
    return {
        "directed": True, "multigraph": False, "graph": {},
        "nodes": nodes,
        "links": [{"source": s, "target": t, "relation": r} for s, t, r in edges],
    }


def run(script: str, *args: str, kb: Path, repo: Path) -> subprocess.CompletedProcess:
    # KB resolves via the KB_ROOT env (honored by every script through kb_graph);
    # no positional kb_root, since kb-query.py treats argv[1] as its command.
    env = dict(os.environ)
    env["KB_ROOT"] = str(kb)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        cwd=str(repo), env=env, text=True, capture_output=True,
    )


# Shared fixture: a hub file (core.py) undocumented + a peripheral file (util.py)
# documented. core.py degree clearly > util.py.
def coverage_fixture(repo: Path) -> Path:
    g = graph(
        nodes=[
            node("core_py", "core.py", "core.py", 1),
            node("core_run", "run()", "core.py", 10),
            node("core_step", "step()", "core.py", 20),
            node("core_help", "helper()", "core.py", 30),
            node("util_py", "util.py", "util.py", 1),
            node("util_fmt", "fmt()", "util.py", 5),
        ],
        edges=[
            ("core_py", "core_run", "contains"),
            ("core_py", "core_step", "contains"),
            ("core_py", "core_help", "contains"),
            ("core_run", "core_step", "calls"),
            ("core_run", "core_help", "calls"),
            ("core_step", "core_help", "calls"),
            ("core_run", "util_fmt", "calls"),
            ("core_step", "util_fmt", "calls"),
            ("core_help", "util_fmt", "calls"),
            ("util_py", "util_fmt", "contains"),
        ],
    )
    docs = {
        "peripheral.md": "---\nsources:\n  - util.py\nupdated: 2026-01-01\n---\n# Peripheral\nDocuments util.\n",
    }
    index = {
        "description": "test kb",
        "entries": {"peripheral.md": {"topics": ["util"]}},
    }
    write_kb(repo, index=index, topics=["util", "core"], docs=docs, graph=g)
    return repo / ".claude" / "knowledge"


# --------------------------------------------------------------------------- #
# Tests — kb-coverage.py (coverage)
# --------------------------------------------------------------------------- #

def test_coverage_flags_undocumented_hub():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = coverage_fixture(repo)
        r = run("kb-coverage.py", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        out = r.stdout
        assert "core.py" in out, f"hub core.py not flagged:\n{out}"
        # util.py is documented + peripheral → must NOT appear as a gap.
        gap_region = out.split("Drift")[0]
        assert "util.py" not in gap_region, f"documented util.py listed as gap:\n{out}"
        assert "%" in out, f"no coverage percentage:\n{out}"


def test_coverage_json_parses():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = coverage_fixture(repo)
        r = run("kb-coverage.py", "--json", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert "coverage" in data, data
        gaps = data["coverage"]["gaps"]
        assert any("core.py" in g.get("file", "") for g in gaps), data


# --------------------------------------------------------------------------- #
# Tests — kb-coverage.py (drift)
# --------------------------------------------------------------------------- #

def drift_fixture(repo: Path) -> Path:
    eng = repo / "engine.py"
    eng.write_text("def old_calc():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init engine", date="2026-01-01T00:00:00")
    # later structural change: drop old_calc, add new_calc
    eng.write_text("def new_calc():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "rework engine", date="2026-03-01T00:00:00")

    g = graph(
        nodes=[
            node("engine_py", "engine.py", "engine.py", 1),
            node("eng_new", "new_calc()", "engine.py", 1),
        ],
        edges=[("engine_py", "eng_new", "contains")],
    )
    docs = {
        # doc updated BETWEEN the two commits → engine.py changed since.
        "risk.md": "---\nsources:\n  - engine.py\nupdated: 2026-01-15\n---\n# Risk\nUses engine.\n",
        # has sources but no updated: → drift untracked.
        "notrack.md": "---\nsources:\n  - engine.py\n---\n# Notrack\n",
    }
    index = {"description": "t", "entries": {
        "risk.md": {"topics": ["risk"]}, "notrack.md": {"topics": ["risk"]}}}
    write_kb(repo, index=index, topics=["risk"], docs=docs, graph=g)
    return repo / ".claude" / "knowledge"


def test_drift_names_structural_delta():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = drift_fixture(repo)
        r = run("kb-coverage.py", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        out = r.stdout
        assert "risk.md" in out and "REVIEW" in out, f"drift not flagged:\n{out}"
        assert "new_calc" in out, f"gained symbol not named:\n{out}"
        assert "old_calc" in out, f"dropped symbol not named:\n{out}"


def test_drift_untracked_listed():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = drift_fixture(repo)
        r = run("kb-coverage.py", kb=kb, repo=repo)
        out = r.stdout
        # notrack.md has sources but no updated: → should be surfaced as untracked.
        assert "notrack.md" in out, f"untracked doc not surfaced:\n{out}"


# --------------------------------------------------------------------------- #
# Tests — kb-review-queue.py
# --------------------------------------------------------------------------- #

def review_fixture(repo: Path) -> Path:
    eng = repo / "engine.py"
    caller = repo / "caller.py"
    eng.write_text("def calc():\n    return 1\n")
    caller.write_text("import engine\ndef run():\n    return engine.calc()\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    # commit that TOUCHES engine.py
    eng.write_text("def calc():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "tweak engine calc")

    g = graph(
        nodes=[
            node("engine_py", "engine.py", "engine.py", 1),
            node("eng_calc", "calc()", "engine.py", 1),
            node("caller_py", "caller.py", "caller.py", 1),
            node("caller_run", "run()", "caller.py", 2),
        ],
        edges=[
            ("engine_py", "eng_calc", "contains"),
            ("caller_py", "caller_run", "contains"),
            ("caller_run", "eng_calc", "calls"),
        ],
    )
    docs = {
        "engine_doc.md": "---\nsources:\n  - engine.py\n---\n# Engine\n",
        "caller_doc.md": "---\nsources:\n  - caller.py\n---\n# Caller\n",
    }
    index = {"description": "t", "entries": {
        "engine_doc.md": {"topics": ["x"]}, "caller_doc.md": {"topics": ["x"]}}}
    write_kb(repo, index=index, topics=["x"], docs=docs, graph=g)
    return repo / ".claude" / "knowledge"


def test_review_queue_maps_touched_and_neighbor_docs():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = review_fixture(repo)
        r = run("kb-review-queue.py", "--commit", "HEAD", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        q = (kb / ".kb" / "review-queue.md")
        assert q.exists(), "review-queue.md not written"
        text = q.read_text()
        assert "engine_doc.md" in text, f"touched-file doc missing:\n{text}"
        assert "caller_doc.md" in text, f"neighbor (caller) doc missing:\n{text}"


def test_review_queue_caps_blocks():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = review_fixture(repo)
        for i in range(25):
            # each run appends one block for HEAD
            run("kb-review-queue.py", "--commit", "HEAD", kb=kb, repo=repo)
        text = (kb / ".kb" / "review-queue.md").read_text()
        blocks = text.count("\n## ") + (1 if text.startswith("## ") else 0)
        assert blocks <= 20, f"queue not capped: {blocks} blocks"


# --------------------------------------------------------------------------- #
# Regression guards — refactored scripts must keep working
# --------------------------------------------------------------------------- #

def test_regression_ast_query():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = coverage_fixture(repo)
        for args in (["query", "core"], ["explain", "run"],
                     ["neighbors", "run"], ["path", "run", "fmt"]):
            r = run("kb-query.py", *args, kb=kb, repo=repo)
            assert r.returncode == 0, f"{args} failed: {r.stderr}"
            assert r.stdout.strip(), f"{args} produced no output"


def test_regression_ast_links():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = coverage_fixture(repo)
        r = run("kb-ast-links.py", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr


def test_regression_doctor():
    with tempfile.TemporaryDirectory() as d:
        repo = init_repo(Path(d) / "repo")
        kb = coverage_fixture(repo)
        r = run("kb-doctor.py", kb=kb, repo=repo)
        assert r.returncode == 0, r.stderr
        assert "issue(s)" in r.stdout, r.stdout


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

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
