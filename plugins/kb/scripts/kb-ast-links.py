#!/usr/bin/env python3
"""AST-implied KB connections — which docs SHOULD link, per real code edges.

Cross-references each KB doc's `sources:` provenance against the AST graph
(`kb-ast.py --out`). If code in doc A's sources calls/imports code in doc B's sources,
A and B are related — surface it, especially when they share NO topic tag yet (a
missing connection `clean` can fix by adding a shared topic or cross-ref). Deterministic;
output is a compact doc↔doc list with the code reason, not the graph.

Usage: kb-ast-links.py [kb_root] [--graph <path>]   (default graph: .kb/ast-graph.json)
Exits 2 if the AST graph is missing (run kb-ast.py --out first).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
if _args:
    import os
    os.environ["KB_ROOT"] = str(Path(_args[0]).resolve())

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_graph  # noqa: E402
import kb_ast_lib as lib  # noqa: E402

KB_ROOT = kb_graph._KB_ROOT
_REPO = KB_ROOT.parent.parent


def _default_graph() -> Path:
    """Our own .kb graph if present; else reuse graphify's, if the repo keeps one fresh."""
    own = KB_ROOT / ".kb" / "ast-graph.json"
    if own.exists():
        return own
    for cand in (_REPO / "graphify-out" / "graph.json", KB_ROOT / "graphify-out" / "graph.json"):
        if cand.exists():
            return cand
    return own


GRAPH = (Path(sys.argv[sys.argv.index("--graph") + 1]) if "--graph" in sys.argv
         else _default_graph())

# Relations that imply a real dependency between two code files.
LINK_RELATIONS = {"calls", "imports", "imports_from", "includes", "implements",
                  "uses_static_prop", "references_constant"}


def main() -> int:
    if not GRAPH.exists():
        print(f"No AST graph at {GRAPH} — run:\n"
              f"  python3 ~/.claude/kb/scripts/kb-ast.py <code_root> "
              f"--out {GRAPH}")
        return 2
    data = json.loads(GRAPH.read_text())
    node_file = {n["id"]: n.get("source_file", "") for n in data.get("nodes", [])}

    # file → file dependency edges
    file_edges: set[tuple[str, str]] = set()
    for link in data.get("links", data.get("edges", [])):
        if link.get("relation") not in LINK_RELATIONS:
            continue
        sf, tf = node_file.get(link.get("source"), ""), node_file.get(link.get("target"), "")
        if sf and tf and sf != tf:
            file_edges.add((sf, tf))

    docsrc = lib.doc_sources_map()
    if not docsrc:
        print("No docs carry `sources:` provenance yet — nothing to cross-reference.")
        return 0

    pairs: dict[tuple[str, str], set[str]] = {}
    for sf, tf in file_edges:
        da_list, db_list = lib.docs_for_file(sf, docsrc), lib.docs_for_file(tf, docsrc)
        reason = f"{Path(sf).name}→{Path(tf).name}"
        for da in da_list:
            for db in db_list:
                if da != db:
                    pairs.setdefault(tuple(sorted((da, db))), set()).add(reason)

    doc_topics = kb_graph._load_doc_topics()

    def shares_topic(a: str, b: str) -> bool:
        return bool(doc_topics.get(a, set()) & doc_topics.get(b, set()))

    missing = {k: v for k, v in pairs.items() if not shares_topic(*k)}
    existing = len(pairs) - len(missing)

    print(f"AST-implied doc links — {len(pairs)} pairs ({existing} already share a topic, "
          f"{len(missing)} do NOT):\n")
    if not missing:
        print("  No missing connections — every AST-linked doc pair already shares a topic.")
        return 0
    print("Missing connections (AST says related, no shared topic — consider linking):")
    for (a, b), reasons in sorted(missing.items(), key=lambda x: -len(x[1])):
        why = ", ".join(sorted(reasons)[:4])
        print(f"  {a}  ↔  {b}   ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
