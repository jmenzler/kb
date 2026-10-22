#!/usr/bin/env python3
"""KB Knowledge Graph — deterministic topic-tag graph from index.json files.

Documents are connected by shared topic tags declared in their index.json entries.
Pure Python, zero infrastructure — no embeddings, no Milvus, no Ollama.

Usage from skill:
    import sys; sys.path.insert(0, '~/.claude/kb/scripts')
    from kb_graph import related, files_for, topics, check
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def _resolve_kb_root() -> Path:
    """KB_ROOT env, else the main checkout's KB (a worktree's copy may be stale), else cwd's."""
    import kb_config
    return kb_config.kb_root()

_KB_ROOT = _resolve_kb_root()
# All exclusions live in .claude/knowledge/.kbignore (single source of truth — no
# hardcoded defaults). init seeds it with the baseline (knowledge-graph, graphify-out,
# inbox); clean self-heals it if missing.
def hub_threshold(doc_count: int) -> int:
    """A topic on more docs than this is too broad to imply a real link — a category, not
    an edge. Scales with corpus size (a fixed number can't fit both a 40-doc and a
    5000-doc KB): a tag stops implying relatedness once it spans roughly a fifth of the
    docs, so a genuinely central concept in a big, complex codebase is allowed a
    correspondingly big hub. Floored so tiny KBs don't flag everything."""
    return max(round(0.2 * doc_count), 5)


def kb_config() -> dict:
    """Related-docs settings from the layered KB config (kb_config.py). related_hops: 1 = direct related
    docs only; 2 = direct + friends-of-friends."""
    import kb_config as layered
    h = layered.load(_KB_ROOT).get("related_hops")
    return {"related_hops": 1 if isinstance(h, int) and h <= 1 else 2}


def _load_kbignore() -> list[str]:
    """Patterns from .kbignore — one per line, '#' comments, gitignore-style."""
    f = _KB_ROOT / ".kbignore"
    try:
        raw = f.read_text()
    except OSError:
        return []
    pats = []
    for line in raw.splitlines():
        s = line.strip().rstrip("/")
        if s and not s.startswith("#"):
            pats.append(s)
    return pats


_KBIGNORE = _load_kbignore()
# Bare dir-name patterns double as os.walk prune names.
_EXCLUDE_DIRS = {p for p in _KBIGNORE if "/" not in p and "*" not in p}


def is_excluded(rel: str) -> bool:
    """True if a KB-relative path is excluded by defaults or .kbignore (segment or glob)."""
    parts = Path(rel).parts
    if any(p in _EXCLUDE_DIRS for p in parts):
        return True
    for pat in _KBIGNORE:
        if (fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"{pat}/*")
                or any(fnmatch.fnmatch(p, pat) for p in parts)):
            return True
    return False


# ---------------------------------------------------------------------------
# Index.json parsing
# ---------------------------------------------------------------------------

def _read_index(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _assert_inside_kb(sub_dir: Path, key: str, prefix: str) -> None:
    """A folder entry must stay under the KB root — '../' escapes are a broken index."""
    if not sub_dir.is_relative_to(_KB_ROOT.resolve()):
        raise ValueError(
            f"KB folder entry '{key}' in {prefix or '<root>'}index.json "
            f"escapes the KB root: {sub_dir}"
        )


def _iter_docs():
    """Walk the index tree to arbitrary depth.

    Yields (doc_path, file_entry, ancestors) where `doc_path` is KB-relative,
    `file_entry` is the doc's own index entry, and `ancestors` is the list of folder
    prefixes containing it, outermost first (e.g.
    ['findings/', 'findings/recovery/']) — empty for a root-level doc.

    An index at any level may declare sub-folders in `entries`, using the same
    {folder, description, topics} shape the root index uses; `folder` is relative to
    the index's own directory. Folder-entry topics live on the ancestor list so callers
    can compose inheritance down the chain.
    """
    root_data = _read_index(_KB_ROOT / "index.json")
    if root_data is None:
        return
    yield from _iter_dir("", root_data, [], (_KB_ROOT.resolve(),))


def _iter_dir(prefix: str, data: dict, ancestors: list, chain: tuple):
    """Depth-first, index-order walk of one index.json and its sub-folders."""
    for fname, file_entry in (data.get("files", {}) or {}).items():
        if isinstance(file_entry, dict):
            yield f"{prefix}{fname}", file_entry, ancestors

    for key, entry in (data.get("entries", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        if "folder" not in entry:
            if key.endswith(".md"):
                yield f"{prefix}{key}", entry, ancestors
            continue
        sub = entry["folder"]
        if not sub.endswith("/"):
            sub += "/"
        sub_prefix = f"{prefix}{sub}"
        sub_dir = (_KB_ROOT / sub_prefix).resolve()
        _assert_inside_kb(sub_dir, key, prefix)
        if sub_dir in chain:
            raise ValueError(
                f"KB index cycle: folder entry '{key}' in "
                f"{prefix or '<root>'}index.json points back to {sub_dir}"
            )
        sub_data = _read_index(sub_dir / "index.json")
        if sub_data is None:
            continue
        yield from _iter_dir(sub_prefix, sub_data,
                             ancestors + [(sub_prefix, entry)], chain + (sub_dir,))


def iter_folder_entries():
    """Yield (declaring_prefix, key, folder_prefix, entry) for every folder entry at any
    depth — including ones whose directory or index.json is missing, so integrity checks
    can see them. Descends only where the sub-index actually loads.
    """
    def walk(prefix: str, data: dict, chain: tuple):
        for key, entry in (data.get("entries", {}) or {}).items():
            if not isinstance(entry, dict) or "folder" not in entry:
                continue
            sub = entry["folder"]
            if not sub.endswith("/"):
                sub += "/"
            sub_prefix = f"{prefix}{sub}"
            yield prefix, key, sub_prefix, entry
            sub_dir = (_KB_ROOT / sub_prefix).resolve()
            _assert_inside_kb(sub_dir, key, prefix)
            if sub_dir in chain:
                raise ValueError(
                    f"KB index cycle: folder entry '{key}' in "
                    f"{prefix or '<root>'}index.json points back to {sub_dir}"
                )
            sub_data = _read_index(sub_dir / "index.json")
            if sub_data is not None:
                yield from walk(sub_prefix, sub_data, chain + (sub_dir,))

    root_data = _read_index(_KB_ROOT / "index.json")
    if root_data is not None:
        yield from walk("", root_data, (_KB_ROOT.resolve(),))


def _ancestor_topics(ancestors: list) -> set[str]:
    """Union of the folder-level tags of every ancestor folder — inheritance composes
    down the whole chain, so a doc carries its own folder's tags and all outer ones."""
    out: set[str] = set()
    for _prefix, entry in ancestors:
        out.update(entry.get("topics", []))
    return out


def _load_doc_topics(inherit: bool = True) -> dict[str, set[str]]:
    """Walk all index.json files, return {doc_path: set_of_topic_tags}.

    Each doc gets the union of its file-specific topics and the categorical topics of
    every folder that contains it, at any nesting depth. Root-level files use their own
    topics only.

    `inherit=False` returns file-level topics only. A folder tag is shared by every
    doc in the folder, so counting it as a shared-topic edge turns each folder into a
    complete subgraph — use `inherit=False` for whole-KB connectivity metrics, where
    that would swamp the real links. Docs with no file-level topics are still keyed
    (empty set) so they surface as isolated rather than vanishing from the graph.
    """
    doc_topics: dict[str, set[str]] = {}
    for doc, entry, ancestors in _iter_docs():
        own = set(entry.get("topics", []))
        if ancestors:
            merged = own | (_ancestor_topics(ancestors) if inherit else set())
            if merged or not inherit:
                doc_topics[doc] = merged
        elif own:
            # Root-level doc: no folder to inherit from, and untagged root docs were
            # never keyed — kept so `check()` still reports them as orphans.
            doc_topics[doc] = own
    return doc_topics


def folder_groups() -> dict[str, list[str]]:
    """{folder_prefix: [doc_paths]} — category membership from folder entries at every
    depth. What folder-level tags actually express, kept out of the edge count.

    A nested doc is a member of its immediate folder AND of every ancestor folder,
    mirroring topic inheritance: an ancestor's tag really is on the doc, so the group
    that names that tag really does contain it.
    """
    groups: dict[str, list[str]] = {}
    for doc, _entry, ancestors in _iter_docs():
        for prefix, _folder_entry in ancestors:
            groups.setdefault(prefix, []).append(doc)
    return {f: sorted(docs) for f, docs in groups.items() if docs}


def doc_descriptions() -> dict[str, str]:
    """{doc_path: description} from index.json entries, at every nesting depth.

    Lets the related-files hook show *what* a doc is about, so the reader can judge
    relevance without resolving and opening it.
    """
    out: dict[str, str] = {}
    for doc, entry, _ancestors in _iter_docs():
        desc = entry.get("description", "")
        if desc:
            out[doc] = desc
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def related(file_path: str, exclude_same_folder: bool = True) -> str:
    """Find KB files sharing the most topic tags with file_path.

    Args:
        file_path: KB-relative path (e.g. 'hedging/lifecycle.md')
        exclude_same_folder: If True, skip results in the same folder as file_path.
    """
    doc_topics = _load_doc_topics()
    my_topics = doc_topics.get(file_path)
    if not my_topics:
        return f"No topics found for '{file_path}'. Add it to an index.json file."

    my_folder = file_path.rsplit("/", 1)[0] if "/" in file_path else ""

    def _skip(other: str) -> bool:
        if other == file_path:
            return True
        parts = other.split("/")
        if any(d in _EXCLUDE_DIRS for d in parts):
            return True
        if exclude_same_folder and my_folder:
            other_folder = other.rsplit("/", 1)[0] if "/" in other else ""
            if other_folder == my_folder:
                return True
        return False

    scored: list[tuple[str, int, str]] = []
    for other_doc, other_topics in doc_topics.items():
        if _skip(other_doc):
            continue
        shared = my_topics & other_topics
        if shared:
            scored.append((other_doc, len(shared), ", ".join(sorted(shared))))

    if not scored:
        return "No related files found."

    scored.sort(key=lambda x: x[1], reverse=True)

    lines = [f"Files related to '{file_path}':"]
    for doc, score, label in scored[:25]:
        lines.append(f"  {doc}: {score} tag(s) — {label}")
    return "\n".join(lines)


def files_for(topic: str) -> str:
    """List all docs tagged with a topic."""
    doc_topics = _load_doc_topics()
    matches = [(doc, topics) for doc, topics in doc_topics.items() if topic in topics]
    matches.sort(key=lambda x: x[0])

    if not matches:
        return f"No documents found for topic '{topic}'."

    lines = [f"Documents for topic '{topic}':"]
    for doc, _ in matches:
        lines.append(f"  {doc}")
    return "\n".join(lines)


def topics(file_path: str) -> str:
    """List all topic tags assigned to a doc."""
    doc_topics = _load_doc_topics()
    my_topics = doc_topics.get(file_path)

    if not my_topics:
        return f"No topics found for '{file_path}'. Add it to an index.json file."

    lines = [f"Topics for '{file_path}':"]
    for t in sorted(my_topics):
        lines.append(f"  {t}")
    return "\n".join(lines)


def related_with_hops(file_path: str, exclude_same_folder: bool = True) -> str:
    """Direct + 1-hop related files. Compact inline format for LLM consumption."""
    doc_topics = _load_doc_topics()
    my_topics = doc_topics.get(file_path)
    if not my_topics:
        return f"No topics found for '{file_path}'."

    my_folder = file_path.rsplit("/", 1)[0] if "/" in file_path else ""

    # Hub topics (on too many docs) are too broad to imply a real link — an edge that
    # exists only via a hub topic is noise, so don't count it as a connection.
    topic_count: dict[str, int] = {}
    for topics_ in doc_topics.values():
        for t in topics_:
            topic_count[t] = topic_count.get(t, 0) + 1
    hubs = {t for t, c in topic_count.items() if c > hub_threshold(len(doc_topics))}

    def _shared(a: set[str], b: set[str]) -> set[str]:
        s = a & b
        non_hub = s - hubs
        return non_hub if non_hub else set()

    def _skip(other: str) -> bool:
        if other == file_path:
            return True
        parts = other.split("/")
        if any(d in _EXCLUDE_DIRS for d in parts):
            return True
        if exclude_same_folder and my_folder:
            other_folder = other.rsplit("/", 1)[0] if "/" in other else ""
            if other_folder == my_folder:
                return True
        return False

    # Direct: doc -> shared (non-hub) topics with file_path
    direct: dict[str, set[str]] = {}
    for other_doc, other_topics in doc_topics.items():
        if _skip(other_doc):
            continue
        shared = _shared(my_topics, other_topics)
        if shared:
            direct[other_doc] = shared

    if not direct:
        return f"No related files found for '{file_path}'."

    direct_sorted = sorted(direct.items(), key=lambda x: len(x[1]), reverse=True)

    # For each direct hit, compute its 1-hop neighbors (excluding file_path and other direct hits)
    seen: set[str] = {file_path} | set(direct.keys())

    # Build stem→count once for disambiguation (only prefix ambiguous names)
    stem_counts: dict[str, int] = {}
    for doc in doc_topics:
        s = Path(doc).stem
        stem_counts[s] = stem_counts.get(s, 0) + 1

    def _short(doc: str) -> str:
        name = Path(doc).stem
        if stem_counts.get(name, 0) <= 1:
            return name
        # Ambiguous: prefix with folder initial
        p = Path(doc).parent.name
        return f"{p[0]}/{name}" if p else name

    def _collapse(stems: list[str]) -> str:
        # Fold a deduped stem list into "prefix-{a, b}" groups (token before first '-')
        # so shared folders aren't reprinted. Singletons and prefixed names stay whole.
        groups: dict[str, list[str]] = {}
        singles: list[str] = []
        for s in stems:
            if "/" in s or "-" not in s:
                singles.append(s)
                continue
            pref, rest = s.split("-", 1)
            groups.setdefault(pref, []).append(rest)
        parts: list[str] = []
        for pref in sorted(groups):
            rests = sorted(groups[pref])
            parts.append(f"{pref}-{rests[0]}" if len(rests) == 1 else f"{pref}-{{{', '.join(rests)}}}")
        return ", ".join(parts + sorted(singles))

    show_hops = kb_config()["related_hops"] >= 2

    lines: list[str] = []
    for d_doc, d_shared in direct_sorted[:15]:
        entry = f"  {_short(d_doc)} ({','.join(sorted(d_shared))})"
        if show_hops:
            d_topics = doc_topics.get(d_doc, set())
            hops = {o for o, ot in doc_topics.items()
                    if o not in seen and not _skip(o) and _shared(d_topics, ot)}
            seen.update(hops)
            # Each hop listed ONCE; the direct link tag carries the "why", hops are friends-of-friends.
            if hops:
                entry += " -> " + _collapse(sorted(_short(h) for h in hops)[:10])
        lines.append(entry)

    return "\n".join(lines)


def resolve_file(name: str) -> str:
    """Resolve a basename (or disambiguated prefix/name) to full KB-relative path(s).

    Handles stems (no .md) and the compact disambiguation format: 'f/overview'
    means overview.md in a folder starting with 'f' (future-optimizations/).
    """
    doc_topics = _load_doc_topics()
    if "/" in name:
        prefix, fname = name.split("/", 1)
        fname = fname.removesuffix(".md")
        matches = [d for d in doc_topics if Path(d).stem == fname and Path(d).parent.name.startswith(prefix)]
    else:
        name = name.removesuffix(".md")
        matches = [d for d in doc_topics if Path(d).stem == name]
    if not matches:
        return f"No file matching '{name}' in KB."
    if len(matches) == 1:
        return matches[0]
    return "\n".join(matches)


def check() -> str:
    """Verify all KB markdown files have at least one topic tag."""
    doc_topics = _load_doc_topics()

    orphaned = []
    for dirpath, dirnames, filenames in os.walk(_KB_ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _EXCLUDE_DIRS]
        rel_dir = Path(dirpath).relative_to(_KB_ROOT)
        for f in filenames:
            if not f.endswith(".md"):
                continue
            if f == "topics.json":
                continue
            rel = str(rel_dir / f) if str(rel_dir) != "." else f
            if is_excluded(rel):
                continue
            if rel not in doc_topics:
                orphaned.append(rel)

    if orphaned:
        lines = [f"WARNING: {len(orphaned)} doc(s) have no topic tags in any index.json:"]
        for path in sorted(orphaned):
            lines.append(f"  {path}")
        return "\n".join(lines)

    return f"OK — all {len(doc_topics)} docs have at least one topic tag."
