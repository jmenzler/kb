#!/usr/bin/env python3
"""KB full-graph analysis — whole-KB connectivity, not per-file related.

Builds the complete shared-topic graph over all KB docs and reports the
structural signals `clean` uses to prioritize curation:
  - degree centrality   : link count per doc (hubs = high value)
  - isolated docs        : degree 0 (tagged but graph-unreachable → merge/link)
  - islands              : connected components (disconnected sub-graphs)
  - hub topics           : topics on too many docs (over-broad → noisy edges)
  - folder groups        : category membership, reported apart from connectivity

Edges come from **file-level** topics only. Folder-level tags are inherited by every
doc in their folder, so counting them would make each folder a complete subgraph and
flatten every degree; they are reported as folder groups instead.

Structure only. Which docs *should* link, and which new topics to add, is
semantic judgment left to the agent reading the docs — this just hands it the
skeleton.

Usage:
  kb-graph-full.py [kb_root]            text report
  kb-graph-full.py [kb_root] --json     machine-readable
  kb-graph-full.py [kb_root] --mermaid  graph diagram for visualization
Always exits 0.
"""

from __future__ import annotations

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


def _edges(doc_topics: dict[str, set[str]]) -> dict[tuple[str, str], set[str]]:
    """Undirected edges keyed (a,b) a<b → all shared topics (truthful connectivity)."""
    topic_docs: dict[str, list[str]] = {}
    for doc, topics in doc_topics.items():
        for t in topics:
            topic_docs.setdefault(t, []).append(doc)
    edges: dict[tuple[str, str], set[str]] = {}
    for topic, docs in topic_docs.items():
        for i in range(len(docs)):
            for j in range(i + 1, len(docs)):
                a, b = sorted((docs[i], docs[j]))
                edges.setdefault((a, b), set()).add(topic)
    return edges


def _components(nodes: set[str], edges: dict[tuple[str, str], set[str]]) -> list[list[str]]:
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[str, list[str]] = {}
    for n in nodes:
        groups.setdefault(find(n), []).append(n)
    return sorted(groups.values(), key=len, reverse=True)


def analyze() -> dict:
    doc_topics = kb_graph._load_doc_topics(inherit=False)
    nodes = set(doc_topics)
    edges = _edges(doc_topics)

    degree: dict[str, int] = {n: 0 for n in nodes}
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1

    topic_docs: dict[str, int] = {}
    for topics in doc_topics.values():
        for t in topics:
            topic_docs[t] = topic_docs.get(t, 0) + 1

    thr = kb_graph.hub_threshold(len(nodes))
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "degree": dict(sorted(degree.items(), key=lambda x: -x[1])),
        "isolated": sorted(n for n in nodes if degree[n] == 0),
        "islands": [c for c in _components(nodes, edges) if len(c) > 1][1:],  # drop main component
        "hub_threshold": thr,
        "folder_groups": {f: len(docs) for f, docs in kb_graph.folder_groups().items()},
        "hub_topics": sorted(
            ((t, c) for t, c in topic_docs.items() if c > thr),
            key=lambda x: -x[1],
        ),
        "_edges": edges,
    }


def _mermaid(a: dict) -> str:
    lines = ["graph LR"]
    for (x, y), shared in a["_edges"].items():
        lx, ly = Path(x).stem, Path(y).stem
        lines.append(f'  {abs(hash(x))%99999}["{lx}"] --- {abs(hash(y))%99999}["{ly}"]')
    return "\n".join(lines)


def main() -> int:
    a = analyze()
    if "--json" in _flags:
        a.pop("_edges")
        print(json.dumps(a, indent=2))
        return 0
    if "--mermaid" in _flags:
        print(_mermaid(a))
        return 0

    print(
        f"KB graph — {a['node_count']} docs, {a['edge_count']} edges "
        "(file-level topics; folder tags are membership, not links)\n"
    )

    if a["folder_groups"]:
        groups = " · ".join(f"{f} {n} docs" for f, n in sorted(a["folder_groups"].items()))
        print(f"Folder groups (inherited category tags): {groups}\n")

    top = list(a["degree"].items())[:10]
    print("Top hubs (most connected — keep accurate, review first):")
    for doc, deg in top:
        print(f"    {deg:>3}  {doc}")

    print(f"\nIsolated docs ({len(a['isolated'])}) — tagged but share no topic with anything:")
    for d in a["isolated"]:
        print(f"    {d}")

    if a["islands"]:
        print(f"\nIslands ({len(a['islands'])}) — disconnected sub-graphs:")
        for c in a["islands"]:
            print(f"    {{{', '.join(sorted(c))}}}")

    if a["hub_topics"]:
        print(f"\nHub topics (>{a['hub_threshold']} docs — too broad, weakens routing):")
        for t, c in a["hub_topics"]:
            print(f"    {c:>3}  {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
