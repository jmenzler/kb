#!/usr/bin/env python3
"""Query the KB across BOTH graphs — the AST code graph and the topic doc graph — joined
by `sources:` provenance. Zero dependencies (plain-dict adjacency, no networkx).

  kb-query.py query "<question>" [--dfs] [--budget N]   traverse from matching nodes/docs
  kb-query.py path "A" "B"                              shortest path between two concepts
  kb-query.py explain "X"                               a node/doc + everything it connects to
  kb-query.py neighbors "X"                             direct neighbors only

By default both layers are searched and shown, sectioned CODE / DOCS, with the bridge
between them (a symbol's documenting doc; a doc's documented symbols). Scope with:
  --ast    code graph only (symbols, calls/imports — needs .kb/ast-graph.json)
  --docs   topic graph only (docs ↔ shared topics — works on prose KBs, no AST needed)

AST graph: .kb/ast-graph.json (build with kb-ast.py), or graphify-out/graph.json; override
--graph <path>. Topic graph: derived from index.json topic tags. Answer from the printed
subgraph only — cite source_file:loc and doc paths; don't invent edges.
"""
from __future__ import annotations

import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_ast_lib as lib  # noqa: E402
import kb_graph  # noqa: E402

Graph = lib.Graph

WANT_AST = "--docs" not in sys.argv      # default both; --docs suppresses code layer
WANT_DOCS = "--ast" not in sys.argv      # default both; --ast suppresses doc layer
_FLAGS = {"--ast", "--docs", "--dfs"}
_VALUE_OPTS = {"--graph", "--budget"}


def _positionals(argv: list[str]) -> list[str]:
    """Positional args — skip flags and the value following each value-taking opt.

    One pass tracking the previous token; `.index()` re-scan mislocates repeated tokens.
    """
    pos, skip = [], False
    for tok in argv:
        if skip:
            skip = False
        elif tok in _VALUE_OPTS:
            skip = True
        elif tok not in _FLAGS and not tok.startswith("--"):
            pos.append(tok)
    return pos


def _opt_int(name: str, default: int) -> int:
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                pass
    return default


# --------------------------------------------------------------------------- #
# AST (code) layer — ported from the former kb-ast-query
# --------------------------------------------------------------------------- #
_DOC_SOURCES: dict[str, list[str]] | None = None


def _sources_map() -> dict[str, list[str]]:
    global _DOC_SOURCES
    if _DOC_SOURCES is None:
        _DOC_SOURCES = lib.doc_sources_map()
    return _DOC_SOURCES


def _doc_note(G: Graph, nid: str) -> str:
    return lib.doc_note(G, nid, _sources_map())


def _load_ast() -> Graph | None:
    p = lib.graph_path()
    if not p:
        return None
    return lib.load_graph(p)


_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")
_CLASS_SUFFIXES = {"impl", "config", "base", "abstract", "service",
                   "manager", "factory", "client", "adapter"}


def _label_tokens(label: str) -> set[str]:
    """Lowercase tokens from a label, including camelCase + snake_case splits.

    So `RiskEngineImpl` → {risk, engine, impl}, matching multi-word queries.
    """
    toks = {t.lower() for t in re.split(r"\W+", label) if t}
    toks |= {m.group(0).lower() for m in _CAMEL_RE.finditer(label)}
    return toks


def _find_code(G: Graph, term: str, n: int = 3) -> list[str]:
    words = [w for w in term.lower().split() if len(w) > 2]
    word_set = set(words)
    scored = []
    for nid in G.attr:
        lab = G.label(nid)
        ll = lab.lower()
        toks = _label_tokens(lab)
        hits = sum(1 for w in words if w in ll)
        if not hits:
            continue
        tok_hits = sum(1 for w in words if w in toks)
        score = hits * 10 + 4 * tok_hits
        if tok_hits == len(words) and len(words) > 1:
            score += 8
        # Class-like labels (TitleCase, no parens) beat factories/tests when
        # the query is a noun phrase.
        is_class = lab[:1].isupper() and not lab.endswith(")") and "." not in lab
        if is_class:
            score += 5
            # Bonus when extras beyond the query are only class-suffix noise.
            if toks - word_set <= _CLASS_SUFFIXES:
                score += 6
        sf = G.attr[nid].get("source_file") or ""
        if sf.startswith("tests/"):
            score -= 5
        if len(lab) <= 40:
            score += 6
        if G.attr[nid].get("file_type") == "code":
            score += 3
        score -= len(lab) // 40
        scored.append((score, nid))
    scored.sort(key=lambda x: -x[0])
    return [nid for _, nid in scored[:n]]


# --------------------------------------------------------------------------- #
# Topic (doc) layer — shared-topic adjacency over index.json
# --------------------------------------------------------------------------- #
def _topic_graph() -> tuple[dict[str, set[str]], dict[str, dict[str, set[str]]], dict[str, str]]:
    doc_topics = kb_graph._load_doc_topics()                 # doc -> {topics}
    descriptions = kb_graph.doc_descriptions()               # doc -> description
    counts: dict[str, int] = {}
    for ts in doc_topics.values():
        for t in ts:
            counts[t] = counts.get(t, 0) + 1
    hub = {t for t, c in counts.items() if c > kb_graph.hub_threshold(len(doc_topics))}
    docs = list(doc_topics)
    adj: dict[str, dict[str, set[str]]] = {d: {} for d in docs}
    for i, a in enumerate(docs):
        ta = doc_topics[a] - hub
        if not ta:
            continue
        for b in docs[i + 1:]:
            sh = ta & (doc_topics[b] - hub)
            if sh:
                adj[a].setdefault(b, set()).update(sh)
                adj[b].setdefault(a, set()).update(sh)
    return doc_topics, adj, descriptions


def _find_docs(doc_topics: dict[str, set[str]], descr: dict[str, str], term: str, n: int = 3) -> list[str]:
    words = [w for w in term.lower().split() if len(w) > 2]
    scored = []
    for d in doc_topics:
        s = 0
        dl = d.lower()
        if any(w in dl for w in words):
            s += 5
        hay = (descr.get(d, "") + " " + " ".join(doc_topics[d])).lower()
        s += sum(1 for w in words if w in hay)
        if s:
            scored.append((s, d))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:n]]


def _docs_for_symbol(G: Graph, nid: str) -> list[str]:
    """The doc(s) documenting a code node, via the provenance bridge."""
    sf = (G.attr.get(nid, {}).get("source_file") or "").lstrip("/")
    if not sf:
        return []
    out = []
    for doc, srcs in _sources_map().items():
        if any(sf == s.lstrip("/") or sf.endswith("/" + s.lstrip("/")) or s.lstrip("/").endswith("/" + sf)
               for s in srcs):
            out.append(doc)
    return sorted(set(out))


_DOC_NEIGHBOR_CAP = 10


def _rank_doc_neighbors(nb_map: dict[str, set[str]]) -> list[tuple[str, set[str]]]:
    """Sort by shared-topic count desc; drop single-shared links when stronger exist; cap.

    Cuts the broad-topic noise tail — a 1-shared-topic link is signal only when
    nothing stronger is around.
    """
    ranked = sorted(nb_map.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if any(len(sh) >= 2 for _, sh in ranked):
        ranked = [(d, sh) for d, sh in ranked if len(sh) >= 2]
    return ranked[:_DOC_NEIGHBOR_CAP]


def _symbols_for_doc(G: Graph | None, doc: str) -> list[str]:
    """Code nodes a doc documents, via its sources: paths."""
    if G is None:
        return []
    srcs = [s.lstrip("/") for s in _sources_map().get(doc, [])]
    if not srcs:
        return []
    hit = []
    for nid, d in G.attr.items():
        sf = (d.get("source_file") or "").lstrip("/")
        if sf and any(sf == s or sf.endswith("/" + s) or s.endswith("/" + sf) for s in srcs):
            hit.append(nid)
    return hit


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_neighbors(G: Graph | None, term: str) -> None:
    if WANT_AST and G is not None:
        hits = _find_code(G, term, 1)
        if hits:
            nid = hits[0]
            print(f"CODE — {G.label(nid)} [{G.loc(nid)}]{_doc_note(G, nid)} neighbors:")
            for v in {n for n, _ in G.undirected(nid)}:
                print(f"  {G.label(v)} [{G.loc(v)}]")
    if WANT_DOCS:
        doc_topics, adj, descr = _topic_graph()
        docs = _find_docs(doc_topics, descr, term, 1)
        if docs:
            d = docs[0]
            print(f"DOCS — {d}  neighbors:")
            for nb, sh in _rank_doc_neighbors(adj[d]):
                print(f"  {nb} — {', '.join(sorted(sh))}")


def cmd_explain(G: Graph | None, term: str) -> None:
    if WANT_AST and G is not None:
        hits = _find_code(G, term, 1)
        if hits:
            nid = hits[0]
            print(f"CODE — {G.label(nid)} [{G.loc(nid)}]  degree={G.degree(nid)}{_doc_note(G, nid)}")
            print("  OUT:")
            for v, r in G.out.get(nid, []):
                print(f"    --{r}--> {G.label(v)} [{G.loc(v)}]")
            print("  IN:")
            for u, r in G.inc.get(nid, []):
                print(f"    {G.label(u)} --{r}-->")
    if WANT_DOCS:
        doc_topics, adj, descr = _topic_graph()
        docs = _find_docs(doc_topics, descr, term, 1)
        if docs:
            d = docs[0]
            print(f"DOCS — {d}  topics: {', '.join(sorted(doc_topics[d])) or '(none)'}")
            print("  related (by shared topic):")
            for nb, sh in _rank_doc_neighbors(adj[d]):
                print(f"    {nb} — {', '.join(sorted(sh))}")
            syms = _symbols_for_doc(G, d) if WANT_AST else []
            if syms:
                print("  documents (code):")
                for nid in syms[:12]:
                    print(f"    {G.label(nid)} [{G.loc(nid)}]")


def cmd_query(G: Graph | None, question: str) -> None:
    dfs = "--dfs" in sys.argv
    budget = _opt_int("--budget", 2000)
    if WANT_AST and G is not None:
        starts = _find_code(G, question)
        if starts:
            nodes: set[str] = set(starts)
            edges: list[tuple[str, str]] = []
            if dfs:
                seen, stack = set(), [(s, 0) for s in reversed(starts)]
                while stack:
                    cur, depth = stack.pop()
                    if cur in seen or depth > 6:
                        continue
                    seen.add(cur)
                    nodes.add(cur)
                    for nb, _ in G.undirected(cur):
                        if nb not in seen:
                            stack.append((nb, depth + 1))
                            edges.append((cur, nb))
            else:
                frontier = set(starts)
                for _ in range(3):
                    nxt = set()
                    for u in frontier:
                        for v, _ in G.undirected(u):
                            if v not in nodes:
                                nxt.add(v)
                                edges.append((u, v))
                    nodes |= nxt
                    frontier = nxt
            qw = question.lower().split()
            lines = [f"CODE — {'DFS' if dfs else 'BFS'} from {[G.label(s) for s in starts]} — {len(nodes)} nodes"]
            for nid in sorted(nodes, key=lambda x: -sum(1 for w in qw if w in G.label(x).lower())):
                lines.append(f"  NODE {G.label(nid)} [{G.loc(nid)}]{_doc_note(G, nid)}")
            for u, v in edges:
                if u in nodes and v in nodes:
                    lines.append(f"  EDGE {G.label(u)} --{G.rel(u, v)}--> {G.label(v)}")
            out = "\n".join(lines)
            print(out[: budget * 4] + ("\n… (truncated; --budget N)" if len(out) > budget * 4 else ""))
    if WANT_DOCS:
        doc_topics, adj, descr = _topic_graph()
        docs = _find_docs(doc_topics, descr, question)
        if docs:
            print(f"DOCS — match: {', '.join(docs)}")
            shown = set(docs)
            for d in docs:
                for nb, sh in _rank_doc_neighbors(adj[d]):
                    print(f"  {d} ↔ {nb} — {', '.join(sorted(sh))}")
                    shown.add(nb)


def cmd_path(G: Graph | None, a: str, b: str) -> None:
    # Code path if both ends resolve to symbols; else topic path between docs;
    # else bridge: a's documenting doc → topic path → b.
    if WANT_AST and G is not None:
        sa, sb = _find_code(G, a, 1), _find_code(G, b, 1)
        if sa and sb:
            p = _bfs(lambda x: [n for n, _ in G.undirected(x)], sa[0], sb[0])
            if p:
                print(f"CODE — path ({len(p)-1} hops):")
                for i, nid in enumerate(p):
                    suf = f"  --{G.rel(nid, p[i+1])}-->" if i < len(p) - 1 else ""
                    print(f"  {G.label(nid)} [{G.loc(nid)}]{_doc_note(G, nid)}{suf}")
                return
    if WANT_DOCS:
        doc_topics, adj, descr = _topic_graph()
        da, db = _find_docs(doc_topics, descr, a, 1), _find_docs(doc_topics, descr, b, 1)
        if da and db:
            p = _bfs(lambda x: list(adj[x]), da[0], db[0])
            if p:
                print(f"DOCS — path ({len(p)-1} hops):")
                for i, d in enumerate(p):
                    sh = ", ".join(sorted(adj[d].get(p[i+1], set()))) if i < len(p) - 1 else ""
                    print(f"  {d}" + (f"  --[{sh}]-->" if sh else ""))
                return
    print(f"No path found between {a!r} and {b!r} in the selected layer(s).")


def _bfs(neighbors, src: str, tgt: str) -> list[str] | None:
    prev: dict[str, str | None] = {src: None}
    q = deque([src])
    while q:
        cur = q.popleft()
        if cur == tgt:
            break
        for nb in neighbors(cur):
            if nb not in prev:
                prev[nb] = cur
                q.append(nb)
    if tgt not in prev:
        return None
    path, cur = [], tgt
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def main() -> int:
    pos = _positionals(sys.argv[1:])
    if not pos:
        print(__doc__)
        return 1
    cmd, rest = pos[0], pos[1:]
    G = _load_ast() if WANT_AST else None
    if WANT_AST and G is None and not WANT_DOCS:
        print("No AST graph found. Build it:\n"
              "  python3 ~/.claude/kb/scripts/kb-ast.py <code_root> "
              "--out .claude/knowledge/.kb/ast-graph.json")
        return 2
    if cmd == "query" and rest:
        cmd_query(G, rest[0]); return 0
    if cmd == "path" and len(rest) >= 2:
        cmd_path(G, rest[0], rest[1]); return 0
    if cmd == "explain" and rest:
        cmd_explain(G, rest[0]); return 0
    if cmd == "neighbors" and rest:
        cmd_neighbors(G, rest[0]); return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
