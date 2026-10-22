#!/usr/bin/env python3
"""Commit-time KB impact — which docs a commit may have staled.

Run by the post-commit hook (after the AST graph is refreshed). Maps the commit's
touched code files plus their 1-hop AST neighbours (callers/callees) to the KB docs
that cite them via `sources:`, and appends a block to `.kb/review-queue.md`. `clean`
drains that queue: it's the "what to re-read" list accumulated since the last clean.

Usage: kb-review-queue.py [kb_root] [--commit <ref>] [--graph <path>]
Silent no-op (exit 0) when there is no graph, no KB, or no touched code.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

def _positionals(argv: list[str]) -> list[str]:
    """argv positionals, skipping flags and the values of value-taking options."""
    value_opts = {"--commit", "--graph"}
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in value_opts:
            skip = True
            continue
        if a.startswith("--"):
            continue
        out.append(a)
    return out


_args = _positionals(sys.argv[1:])
if _args:
    os.environ["KB_ROOT"] = str(Path(_args[0]).resolve())

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_graph  # noqa: E402
import kb_ast_lib as lib  # noqa: E402

KB_ROOT = kb_graph._KB_ROOT
REPO_ROOT = lib.REPO_ROOT
QUEUE = KB_ROOT / ".kb" / "review-queue.md"
MAX_BLOCKS = 20

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".rb", ".c",
            ".cc", ".cpp", ".h", ".hpp", ".cs", ".kt", ".scala", ".php", ".swift",
            ".lua", ".zig", ".ex", ".exs", ".m", ".jl", ".dart", ".sql", ".sh"}


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), *args],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _commit_ref() -> str:
    return sys.argv[sys.argv.index("--commit") + 1] if "--commit" in sys.argv else "HEAD"


def _touched(commit: str) -> list[str]:
    out = _git("diff-tree", "--no-commit-id", "--name-only", "-r", commit)
    if not out:
        return []
    return [f.strip() for f in out.splitlines()
            if f.strip() and Path(f.strip()).suffix in CODE_EXT]


def _nodes_for_file(by_file: dict[str, list[str]], f: str) -> list[str]:
    out: list[str] = []
    for sf, nids in by_file.items():
        if sf.endswith(f) or f.endswith(sf):
            out += nids
    return out


def _trim(text: str) -> str:
    """Keep only the last MAX_BLOCKS `## ` blocks."""
    starts = [m.start() for m in re.finditer(r"(?m)^## ", text)]
    if len(starts) <= MAX_BLOCKS:
        return text
    return text[starts[-MAX_BLOCKS]:]


def main() -> int:
    if not (KB_ROOT / "index.json").exists():
        return 0
    gp = lib.graph_path()
    if not gp:
        return 0
    commit = _commit_ref()
    touched = _touched(commit)
    if not touched:
        return 0

    G = lib.load_graph(gp)
    by_file = lib.code_nodes_by_file(G)
    doc_sources = lib.doc_sources_map()

    # file -> reason; touched wins over neighbour.
    reasons: dict[str, str] = {}
    for f in touched:
        reasons[f] = "touched"
    for f in touched:
        for nid in _nodes_for_file(by_file, f):
            for nb, rel in G.inc.get(nid, []):
                nf = G.attr.get(nb, {}).get("source_file", "")
                if nf and nf not in reasons:
                    reasons[nf] = f"caller of {G.label(nid)}"
            for nb, rel in G.out.get(nid, []):
                nf = G.attr.get(nb, {}).get("source_file", "")
                if nf and nf not in reasons:
                    reasons[nf] = f"callee of {G.label(nid)}"

    # impacted docs: doc -> (file, reason); prefer a touched-file citation.
    doc_hits: dict[str, tuple[str, str]] = {}
    for f, why in reasons.items():
        for doc in lib.docs_for_file(f, doc_sources):
            if doc not in doc_hits or why == "touched":
                doc_hits[doc] = (f, why)

    short = (_git("rev-parse", "--short", commit) or commit).strip()
    subject = (_git("log", "-1", "--format=%s", commit) or "").strip()
    when = (_git("log", "-1", "--format=%ad", "--date=short", commit) or "").strip() \
        or date.today().isoformat()

    lines = [f"## {short} {subject} — {when}"]
    if doc_hits:
        for doc, (f, why) in sorted(doc_hits.items()):
            lines.append(f"- {doc} ← {f} ({why})")
    else:
        lines.append("- (no documented files impacted)")
    block = "\n".join(lines) + "\n"

    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    existing = QUEUE.read_text() if QUEUE.exists() else ""
    combined = (existing.rstrip() + "\n\n" + block) if existing.strip() else block
    QUEUE.write_text(_trim(combined))
    return 0


if __name__ == "__main__":
    sys.exit(main())
