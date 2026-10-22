#!/usr/bin/env python3
"""Shared AST-graph helpers — the one true home for code reused across the AST tools.

A single, importable (underscore-named) module so kb-query, kb-ast-links,
kb-coverage, and kb-review-queue don't each carry their own copy of the graph
loader, the frontmatter parser, and the doc↔file provenance join.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_graph  # noqa: E402

KB_ROOT = kb_graph._KB_ROOT
REPO_ROOT = KB_ROOT.parent.parent  # .claude/knowledge -> repo root


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #

class Graph:
    """Minimal directed graph: node attrs + out/in adjacency with edge relations."""

    def __init__(self) -> None:
        self.attr: dict[str, dict] = {}
        self.out: dict[str, list[tuple[str, str]]] = {}   # id -> [(target, relation)]
        self.inc: dict[str, list[tuple[str, str]]] = {}    # id -> [(source, relation)]

    def add_node(self, nid: str, **a) -> None:
        self.attr.setdefault(nid, {}).update(a)
        self.out.setdefault(nid, [])
        self.inc.setdefault(nid, [])

    def add_edge(self, s: str, t: str, relation: str = "") -> None:
        self.add_node(s)
        self.add_node(t)
        self.out[s].append((t, relation))
        self.inc[t].append((s, relation))

    def label(self, nid: str) -> str:
        return str(self.attr.get(nid, {}).get("label", nid))

    def loc(self, nid: str) -> str:
        d = self.attr.get(nid, {})
        return f"{d.get('source_file', '')}:{d.get('source_location', '')}".rstrip(":")

    def degree(self, nid: str) -> int:
        return len(self.out.get(nid, [])) + len(self.inc.get(nid, []))

    def undirected(self, nid: str) -> list[tuple[str, str]]:
        return self.out.get(nid, []) + self.inc.get(nid, [])

    def rel(self, a: str, b: str) -> str:
        for t, r in self.out.get(a, []):
            if t == b:
                return r
        for t, r in self.out.get(b, []):
            if t == a:
                return r
        return ""


def graph_path(argv: list[str] | None = None) -> Path | None:
    """Resolve the AST graph: --graph override, then .kb/ast-graph.json, then graphify-out."""
    argv = argv if argv is not None else sys.argv
    if "--graph" in argv:
        return Path(argv[argv.index("--graph") + 1])
    for c in (KB_ROOT / ".kb" / "ast-graph.json",
              REPO_ROOT / "graphify-out" / "graph.json",
              KB_ROOT / "graphify-out" / "graph.json"):
        if c.exists():
            return c
    return None


def load_graph(path: Path) -> Graph:
    data = json.loads(path.read_text())
    g = Graph()
    for n in data.get("nodes", []):
        g.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
    for e in data.get("links", data.get("edges", [])):
        g.add_edge(e["source"], e["target"], relation=e.get("relation", ""))
    return g


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #

def frontmatter_block(text: str) -> str | None:
    """The raw YAML-ish block between a leading `---` pair, or None if absent."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return None if end == -1 else text[3:end]


def frontmatter_sources(text: str) -> list[str]:
    """`sources:` paths from a leading frontmatter block (inline or list form).

    Filters `commit:` refs and URLs — only disk-checkable paths. Returns [] when
    there is no frontmatter or no sources (use frontmatter_block to distinguish).
    """
    block = frontmatter_block(text)
    if block is None:
        return []
    out: list[str] = []
    in_src = False
    for raw in block.splitlines():
        s = raw.strip()
        if s.startswith("sources:"):
            in_src = True
            inline = s.split("sources:", 1)[1].strip()
            if inline.startswith("["):
                out += [x.strip().strip("'\"") for x in inline.strip("[]").split(",") if x.strip()]
                in_src = False
            continue
        if in_src:
            if s.startswith("- "):
                out.append(s[2:].strip().strip("'\""))
            elif s and not s.startswith("#"):
                in_src = False
    return [p for p in out if not p.startswith("commit:") and "://" not in p]


def frontmatter_field(text: str, key: str) -> str | None:
    """A scalar `key: value` from the leading frontmatter block (e.g. `updated`)."""
    block = frontmatter_block(text)
    if block is None:
        return None
    prefix = f"{key}:"
    for raw in block.splitlines():
        s = raw.strip()
        if s.startswith(prefix):
            return s[len(prefix):].strip().strip("'\"")
    return None


# --------------------------------------------------------------------------- #
# Doc ↔ source-file provenance join
# --------------------------------------------------------------------------- #

def doc_sources_map(kb_root: Path | None = None) -> dict[str, list[str]]:
    """KB-relative doc → its declared `sources:` paths (docs without sources omitted)."""
    root = kb_root or KB_ROOT
    out: dict[str, list[str]] = {}
    for md in root.rglob("*.md"):
        rel = str(md.relative_to(root))
        if kb_graph.is_excluded(rel):
            continue
        try:
            srcs = frontmatter_sources(md.read_text())
        except OSError:
            continue
        if srcs:
            out[rel] = srcs
    return out


def docs_for_file(source_file: str, doc_sources: dict[str, list[str]]) -> list[str]:
    """Docs whose `sources:` reference source_file (suffix match, either direction)."""
    return sorted(
        d for d, srcs in doc_sources.items()
        if any(source_file.endswith(s) or s.endswith(source_file) for s in srcs)
    )


def doc_note(g: Graph, nid: str, doc_sources: dict[str, list[str]]) -> str:
    """' «doc: ...»' if a KB doc documents this node's source file."""
    sf = g.attr.get(nid, {}).get("source_file", "")
    if not sf:
        return ""
    docs = docs_for_file(sf, doc_sources)
    return f"  «doc: {', '.join(docs)}»" if docs else ""


# --------------------------------------------------------------------------- #
# Code-node aggregates
# --------------------------------------------------------------------------- #

def code_nodes_by_file(g: Graph) -> dict[str, list[str]]:
    """source_file → its code-node ids (file_type == 'code')."""
    out: dict[str, list[str]] = {}
    for nid, d in g.attr.items():
        if d.get("file_type") != "code":
            continue
        sf = d.get("source_file", "")
        if sf:
            out.setdefault(sf, []).append(nid)
    return out


def file_centrality(g: Graph) -> dict[str, int]:
    """source_file → summed degree of its code nodes (a file-level centrality proxy)."""
    return {sf: sum(g.degree(n) for n in nids)
            for sf, nids in code_nodes_by_file(g).items()}
