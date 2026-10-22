#!/usr/bin/env python3
"""KB self-audit — completeness (coverage) + freshness (drift).

Fuses the AST code graph with doc `sources:` provenance to answer two questions the
topic graph can't:
  COVERAGE — which central code has NO doc? (ranked gaps, coverage %)
  DRIFT    — which docs describe code that has moved since their `updated:` date?
             (named structural delta: symbols gained/dropped)

Both are SIGNALS, not commands: coverage gaps are SUGGESTIONS (centrality ≠ always
doc-worthy — the agent judges); drift items are flagged for REVIEW, never auto-rewritten.

Usage: kb-coverage.py [kb_root] [--json] [--graph <path>]   (always exits 0)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

def _positionals(argv: list[str]) -> list[str]:
    """argv positionals, skipping flags and the value of --graph."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--graph":
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
JSON = "--json" in sys.argv

GOD_NODE_TOP = 30   # most-connected code symbols define which files are "central"
MAX_GAPS = 15

# Per-language definition patterns — match a diff line ('+'/'-') that adds or removes
# a top-level symbol. Keyed by file extension; falls back to the python set.
_SYMBOL_RE = {
    ".py": re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)"),
    ".pyi": re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)"),
    ".js": re.compile(r"^[+-]\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+(\w+)"),
    ".jsx": re.compile(r"^[+-]\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class)\s+(\w+)"),
    ".ts": re.compile(r"^[+-]\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type)\s+(\w+)"),
    ".tsx": re.compile(r"^[+-]\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type)\s+(\w+)"),
    ".rs": re.compile(r"^[+-]\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait|impl)\s+(\w+)"),
    ".go": re.compile(r"^[+-]\s*(?:func|type)\s+(\w+)"),
}
_DEFAULT_RE = _SYMBOL_RE[".py"]


def _git(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), *args],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _has_git() -> bool:
    return _git("rev-parse", "--git-dir") is not None


# --------------------------------------------------------------------------- #
# Coverage
# --------------------------------------------------------------------------- #

def _symbol_name(label: str) -> str:
    m = re.match(r"\w+", label)
    return m.group(0) if m else label


def coverage(G: lib.Graph) -> dict:
    centrality = lib.file_centrality(G)
    by_file = lib.code_nodes_by_file(G)
    doc_sources = lib.doc_sources_map()

    # God-nodes: top code symbols by degree → the files holding them are "central".
    code_nodes = [n for n, d in G.attr.items() if d.get("file_type") == "code"]
    code_nodes.sort(key=lambda n: -G.degree(n))
    god_files = {G.attr[n].get("source_file", "") for n in code_nodes[:GOD_NODE_TOP]}
    god_files.discard("")
    central = sorted(god_files, key=lambda f: -centrality.get(f, 0))

    def documented(f: str) -> bool:
        return bool(lib.docs_for_file(f, doc_sources))

    documented_central = [f for f in central if documented(f)]
    gaps = []
    for f in central:
        if documented(f):
            continue
        top_syms = sorted(by_file.get(f, []), key=lambda n: -G.degree(n))[:3]
        gaps.append({"file": f, "centrality": centrality.get(f, 0),
                     "symbols": [G.label(n) for n in top_syms]})
    gaps.sort(key=lambda g: -g["centrality"])

    pct = round(100 * len(documented_central) / len(central), 1) if central else 100.0

    # Trivia: docs whose every matched source file is bottom-quartile centrality.
    vals = sorted(centrality.values())
    q1 = vals[len(vals) // 4] if vals else 0
    trivia = []
    for doc, srcs in doc_sources.items():
        matched = [f for f in centrality
                   if any(f.endswith(s) or s.endswith(f) for s in srcs)]
        if matched and all(centrality[f] <= q1 for f in matched):
            trivia.append(doc)

    return {"pct": pct, "documented": len(documented_central), "central": len(central),
            "gaps": gaps[:MAX_GAPS], "trivia": sorted(trivia)}


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #

def _delta(source_file: str, updated: str, current_syms: set[str]) -> dict | None:
    """Symbols gained/dropped in source_file since `updated`, cross-checked vs AST."""
    log = _git("log", f"--since={updated}", "--format=%H", "--", source_file)
    if not log or not log.strip():
        return None
    commits = len([h for h in log.splitlines() if h.strip()])

    base = _git("rev-list", "-1", f"--until={updated} 23:59:59", "HEAD", "--", source_file)
    base = base.strip() if base else ""
    diff = _git("diff", base, "HEAD", "--", source_file) if base \
        else _git("show", "HEAD", "--", source_file)
    added: set[str] = set()
    removed: set[str] = set()
    rx = _SYMBOL_RE.get(Path(source_file).suffix, _DEFAULT_RE)
    for line in (diff or "").splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        m = rx.match(line)
        if not m:
            continue
        (added if line[0] == "+" else removed).add(m.group(1))
    gained = sorted((added - removed) & current_syms) if current_syms else sorted(added - removed)
    dropped = sorted((removed - added) - current_syms) if current_syms else sorted(removed - added)
    if not gained and not dropped and not commits:
        return None
    return {"file": source_file, "commits": commits, "gained": gained, "dropped": dropped}


def drift(G: lib.Graph) -> dict:
    if not _has_git():
        return {"available": False, "review": [], "untracked": []}
    by_file = lib.code_nodes_by_file(G)
    doc_sources = lib.doc_sources_map()
    review, untracked = [], []
    for doc, srcs in sorted(doc_sources.items()):
        try:
            text = (KB_ROOT / doc).read_text()
        except OSError:
            continue
        updated = lib.frontmatter_field(text, "updated")
        if not updated:
            untracked.append(doc)
            continue
        deltas = []
        for sf in srcs:
            disk = REPO_ROOT / sf
            if not disk.exists():
                continue  # broken provenance — kb-doctor owns that
            # current AST symbols for this file (suffix-matched), for cross-checking.
            cur: set[str] = set()
            for f, nids in by_file.items():
                if f.endswith(sf) or sf.endswith(f):
                    cur |= {_symbol_name(G.label(n)) for n in nids}
            d = _delta(sf, updated, cur)
            if d and (d["gained"] or d["dropped"]):
                deltas.append(d)
        if deltas:
            review.append({"doc": doc, "updated": updated, "files": deltas})
    return {"available": True, "review": review, "untracked": untracked}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def main() -> int:
    gp = lib.graph_path()
    if not gp:
        msg = ("No AST graph (.kb/ast-graph.json) — build it with kb-ast.py --out. "
               "Coverage/drift need the code graph.")
        print(json.dumps({"error": msg}) if JSON else msg)
        return 0
    G = lib.load_graph(gp)
    cov = coverage(G)
    dft = drift(G)

    if JSON:
        print(json.dumps({"coverage": cov, "drift": dft}, indent=2))
        return 0

    print(f"KB self-audit — {KB_ROOT}\n")
    print("== Coverage (SUGGESTIONS — centrality ≠ always doc-worthy; you judge) ==")
    print(f"  {cov['pct']}% of central code files documented "
          f"({cov['documented']}/{cov['central']}).")
    if cov["gaps"]:
        print("  Undocumented hubs (ranked by centrality):")
        for g in cov["gaps"]:
            syms = ", ".join(g["symbols"])
            print(f"    {g['file']}  (centrality {g['centrality']}) — {syms}")
    else:
        print("  No undocumented central files.")
    if cov["trivia"]:
        print("  Low-signal docs (all sources peripheral — consider merging):")
        for d in cov["trivia"]:
            print(f"    {d}")

    print("\n== Drift (flag for REVIEW — never auto-rewrite) ==")
    if not dft["available"]:
        print("  git unavailable — drift needs commit history.")
    elif not dft["review"] and not dft["untracked"]:
        print("  No drift detected; all provenance-dated docs current.")
    else:
        for r in dft["review"]:
            for f in r["files"]:
                parts = []
                if f["gained"]:
                    parts.append("gained " + ", ".join(s + "()" for s in f["gained"]))
                if f["dropped"]:
                    parts.append("dropped " + ", ".join(s + "()" for s in f["dropped"]))
                print(f"  {r['doc']} (updated {r['updated']}, {f['commits']} commit(s) since): "
                      f"{f['file']} {'; '.join(parts)} → REVIEW")
        if dft["untracked"]:
            print("  Drift untracked (has sources: but no updated: — add one to enable):")
            for d in dft["untracked"]:
                print(f"    {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
