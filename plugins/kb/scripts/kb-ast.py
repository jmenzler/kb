#!/usr/bin/env python3
"""Brownfield KB bootstrap helper — deterministic AST skeleton via graphify (tree-sitter).

Emits a COMPACT digest — core abstractions (god-nodes), clusters → files, stats — for an
agent to turn into KB docs. Does NOT print the full graph (thousands of nodes); the raw
graph goes to --out if you want it. The digest is the factual skeleton: real symbols,
file paths, line numbers — no LLM, no hallucination.

Usage:
  kb-ast.py <code_root> [--out graph.json]
Requires graphify ( `uv tool install graphifyy` ). Exits 2 with guidance if absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make graphify importable from its uv-tool install.
for _p in (Path.home() / ".local/share/uv/tools/graphifyy/lib").glob("python*/site-packages"):
    sys.path.insert(0, str(_p))

try:
    from graphify.analyze import god_nodes
    from graphify.build import build_from_json
    from graphify.extract import collect_files, extract
except ImportError:
    print("graphify not installed — run `uv tool install graphifyy` (or `pip install graphifyy`).")
    print("Without it, bootstrap falls back to manual codebase exploration (Glob/Grep/Read).")
    sys.exit(2)


def _communities(G) -> dict[int, list[str]]:
    """Leiden clusters if graspologic is available; else connected components."""
    try:
        from graphify.cluster import cluster
        return cluster(G)
    except Exception:
        import networkx as nx
        UG = G.to_undirected() if G.is_directed() else G
        return {i: list(c) for i, c in enumerate(nx.connected_components(UG))}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: kb-ast.py <code_root> [--out graph.json]")
        return 1
    root = Path(args[0]).resolve()
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None

    files = collect_files(root)
    if not files:
        print(f"No code files under {root}")
        return 1
    # Cache under the KB's .kb/ (gitignored machinery dir) if a KB exists, else a
    # neutral user cache — never litter the source tree.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import kb_graph
        kb_root = kb_graph._KB_ROOT
        cache = (kb_root / ".kb" / "ast-cache") if kb_root.exists() else (Path.home() / ".cache" / "kb-ast")
    except Exception:
        cache = Path.home() / ".cache" / "kb-ast"
    cache.mkdir(parents=True, exist_ok=True)
    ast = extract(files, cache_root=cache)
    G = build_from_json(ast, directed=True)
    comms = _communities(G)

    if out:
        try:
            from graphify.export import to_json
            to_json(G, comms, str(out))
        except Exception:
            out.write_text(json.dumps(ast))

    attrs = dict(G.nodes(data=True))

    def sf(nid: str) -> str:
        return attrs.get(nid, {}).get("source_file", "?")

    def loc(nid: str) -> str:
        return attrs.get(nid, {}).get("source_location", "")

    def lbl(nid: str) -> str:
        return attrs.get(nid, {}).get("label", nid)

    print(f"AST skeleton — {len(files)} files, {G.number_of_nodes()} symbols, "
          f"{G.number_of_edges()} edges\n")

    print("Core abstractions (god-nodes — most-connected; document these first):")
    for g in god_nodes(G, top_n=15):
        nid = g.get("id") or g.get("node") or ""
        deg = g.get("degree", G.degree(nid) if nid in G else "?")
        print(f"  {lbl(nid)}  [{sf(nid)}:{loc(nid)}]  deg={deg}")

    big = sorted(comms.items(), key=lambda x: -len(x[1]))
    print(f"\nClusters ({len(comms)} total — candidate folders/topics; top by size):")
    for cid, members in big[:20]:
        cfiles = sorted({sf(m) for m in members if sf(m) != "?"})
        if not cfiles:
            continue
        print(f"  cluster {cid} — {len(members)} symbols, {len(cfiles)} files:")
        for f in cfiles[:8]:
            print(f"      {f}")
        if len(cfiles) > 8:
            print(f"      … +{len(cfiles) - 8} more files")
    if out:
        print(f"\nFull graph → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
