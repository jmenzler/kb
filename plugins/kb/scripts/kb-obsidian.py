#!/usr/bin/env python3
"""Export the KB as an Obsidian vault — docs + a navigable graph.

Obsidian builds its graph from inline [[wikilinks]] and #tags, which the KB doesn't
carry: its edges live in index.json (topic tags) and .kb/ast-graph.json (AST). This
mirrors every doc into a generated vault and materialises those edges as wikilinks +
`tags:` frontmatter, so Obsidian's graph view and tag pane light up.

The vault is generated and disposable — open `<repo>/kb-vault/` directly as an Obsidian
vault. It lives at the repo root (NOT under `.claude/.../.kb/`) so it's reachable in
Obsidian's folder picker, which hides dot-folders. Edits there are overwritten on the
next run; curate the real KB instead.

Usage: kb-obsidian.py [kb_root] [--out <dir>]   (default out: <repo>/kb-vault)

First run creates the vault. The post-commit hook only regenerates it if the vault
directory already exists (presence = opt-in), so it costs nothing until you init it.
Add `kb-vault/` to the repo `.gitignore` — it's generated, not source.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Graph edge budget — keep it hub-and-spoke, not a mesh. Only doc-doc links with at
# least MIN_SHARED_TOPICS shared (non-hub) topics become edges, capped per doc.
MIN_SHARED_TOPICS = 2
MAX_TOPIC_LINKS = 4
MAX_AST_LINKS = 4

# Distinct hues cycled across groups (Obsidian colorGroups want decimal 0xRRGGBB).
_PALETTE = [0xE6194B, 0x3CB44B, 0xFFE119, 0x4363D8, 0xF58231, 0x911EB4,
            0x42D4F4, 0xF032E6, 0xBFEF45, 0xFABED4, 0x469990, 0xDCBEFF,
            0x9A6324, 0x800000, 0xAAFFC3, 0x808000, 0xFFD8B1, 0x000075]


def _positionals(argv: list[str]) -> list[str]:
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a == "--out":
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


def _obsidian_cfg() -> dict:
    try:
        return json.loads((KB_ROOT / ".kb" / "config.json").read_text()).get("obsidian", {}) or {}
    except (OSError, json.JSONDecodeError):
        return {}


# Vault path precedence: --out arg > .kb/config.json obsidian.path > "kb-vault".
OUT = (Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv
       else lib.REPO_ROOT / str(_obsidian_cfg().get("path", "kb-vault")))

# AST relations that imply a real code dependency between two files (→ a doc link).
LINK_RELATIONS = {"calls", "imports", "imports_from", "includes", "implements",
                  "uses_static_prop", "references_constant"}


def _docs() -> list[str]:
    """KB-relative .md docs, excluding ignored paths and machinery."""
    out = []
    for md in KB_ROOT.rglob("*.md"):
        rel = str(md.relative_to(KB_ROOT))
        if kb_graph.is_excluded(rel) or md.name == "_TEMPLATE.md":
            continue
        out.append(rel)
    return sorted(out)


def _stem_counts(docs: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for d in docs:
        s = Path(d).stem
        counts[s] = counts.get(s, 0) + 1
    return counts


def _wikilink(doc: str, stem_counts: dict[str, int]) -> str:
    """Shortest unambiguous Obsidian target: basename if unique, else path."""
    stem = Path(doc).stem
    if stem_counts.get(stem, 0) <= 1:
        return f"[[{stem}]]"
    return f"[[{doc[:-3]}]]"  # path without .md


def _topic_neighbors(docs: list[str]) -> dict[str, dict[str, set[str]]]:
    """doc → {other_doc: shared non-hub topics}. Mirrors kb_graph hub filtering."""
    doc_topics = kb_graph._load_doc_topics()
    counts: dict[str, int] = {}
    for ts in doc_topics.values():
        for t in ts:
            counts[t] = counts.get(t, 0) + 1
    hubs = {t for t, c in counts.items() if c > kb_graph.hub_threshold(len(doc_topics))}

    present = set(docs)
    neigh: dict[str, dict[str, set[str]]] = {d: {} for d in docs}
    for a in docs:
        ta = doc_topics.get(a, set())
        for b in docs:
            if b == a or b not in present:
                continue
            shared = (ta & doc_topics.get(b, set())) - hubs
            if shared:
                neigh[a][b] = shared
    return neigh


def _ast_neighbors(docs: list[str]) -> dict[str, set[str]]:
    """doc → docs whose `sources:` code is called/imported by this doc's code."""
    gp = lib.graph_path()
    if not gp:
        return {}
    try:
        data = json.loads(gp.read_text())
    except OSError:
        return {}
    node_file = {n["id"]: n.get("source_file", "") for n in data.get("nodes", [])}
    doc_sources = lib.doc_sources_map()
    present = set(docs)

    out: dict[str, set[str]] = {d: set() for d in docs}
    for link in data.get("links", data.get("edges", [])):
        if link.get("relation") not in LINK_RELATIONS:
            continue
        sf = node_file.get(link.get("source"), "")
        tf = node_file.get(link.get("target"), "")
        if not sf or not tf or sf == tf:
            continue
        for da in lib.docs_for_file(sf, doc_sources):
            for db in lib.docs_for_file(tf, doc_sources):
                if da != db and da in present and db in present:
                    out[da].add(db)
                    out[db].add(da)
    return out


def _body_without_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4:].lstrip("\n") if end != -1 else text


def _sanitize_tag(t: str) -> str:
    return t.replace(" ", "-").replace("/", "-")


def _group(doc: str) -> str:
    """Folder-based group: a doc's top-level KB folder, or 'overview' for root docs."""
    parts = doc.split("/")
    return _sanitize_tag(parts[0]) if len(parts) > 1 else "overview"


def _write_group_hubs(out: Path, groups: dict[str, list[str]], stem_counts: dict[str, int],
                      topic_n: dict[str, dict[str, set]], ast_n: dict[str, set]) -> None:
    """One _group-<name>.md hub per folder linking members + connected groups.

    The hub→members links pull each group into a visible star cluster; hub→hub links
    (cross-group edges) keep the groups connected instead of floating apart.
    """
    doc_group = {d: g for g, ds in groups.items() for d in ds}

    # Inter-group edge counts from topic + AST neighbours.
    cross: dict[str, dict[str, int]] = {g: {} for g in groups}
    for doc, gd in doc_group.items():
        nbrs = set(topic_n.get(doc, {})) | ast_n.get(doc, set())
        for nb in nbrs:
            go = doc_group.get(nb)
            if go and go != gd:
                cross[gd][go] = cross[gd].get(go, 0) + 1

    for g, members in groups.items():
        lines = ["---", f"tags: [group/{g}]", "type: group", "---",
                 "<!-- AUTO-GENERATED by kb-obsidian.py -->", "", f"# Group: {g}", "",
                 f"**{len(members)} docs**", "", "## Members"]
        for m in sorted(members):
            lines.append(f"- {_wikilink(m, stem_counts)}")
        conn = sorted(cross[g].items(), key=lambda x: -x[1])
        if conn:
            lines += ["", "## Connected groups"]
            for og, n in conn:
                lines.append(f"- [[_group-{og}]] — {n} link{'s' if n != 1 else ''}")
        lines += ["", f"#group/{g}", ""]
        (out / f"_group-{g}.md").write_text("\n".join(lines))


def _write_graph_config(out: Path, groups: list[str]) -> None:
    """Write .obsidian/graph.json with a color group per folder (the visible grouping).

    Overwrites only graph.json — other .obsidian files (app/workspace/appearance) are
    left as the user set them. Tag-nodes are hidden; groups color by `tag:#group/<x>`.
    """
    cfg_dir = out / ".obsidian"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    color_groups = [
        {"query": f"tag:#group/{g}", "color": {"a": 1, "rgb": _PALETTE[i % len(_PALETTE)]}}
        for i, g in enumerate(sorted(groups))
    ]
    cfg = {
        "collapse-filter": False, "search": "", "showTags": False,
        "showAttachments": False, "hideUnresolved": True, "showOrphans": True,
        "collapse-color-groups": False, "colorGroups": color_groups,
        "collapse-display": False, "showArrow": False, "textFadeMultiplier": 0,
        "nodeSizeMultiplier": 1, "lineSizeMultiplier": 1, "collapse-forces": False,
        "centerStrength": 0.5, "repelStrength": 10, "linkStrength": 1,
        "linkDistance": 250, "scale": 1, "close": False,
    }
    (cfg_dir / "graph.json").write_text(json.dumps(cfg, indent=2))


def _wipe(out: Path) -> None:
    """Clear generated content but keep Obsidian's own .obsidian config dir."""
    if not out.exists():
        out.mkdir(parents=True, exist_ok=True)
        return
    for child in out.iterdir():
        if child.name == ".obsidian":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _mermaid_overview(out: Path) -> None:
    """Best-effort topic-graph overview note (Obsidian renders mermaid)."""
    try:
        mm = subprocess.check_output(
            [sys.executable, str(Path(__file__).resolve().parent / "kb-graph-full.py"), "--mermaid"],
            text=True, stderr=subprocess.DEVNULL, env={**os.environ, "KB_ROOT": str(KB_ROOT)},
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    if "```mermaid" in mm or "graph" in mm:
        (out / "_graph.md").write_text(f"# KB topic graph\n\n{mm}\n")


def main() -> int:
    if not (KB_ROOT / "index.json").exists():
        print(f"No KB at {KB_ROOT}")
        return 0
    docs = _docs()
    if not docs:
        print("No docs to export.")
        return 0

    stem_counts = _stem_counts(docs)
    topic_n = _topic_neighbors(docs)
    ast_n = _ast_neighbors(docs)
    doc_topics = kb_graph._load_doc_topics()

    groups: dict[str, list[str]] = {}
    for doc in docs:
        groups.setdefault(_group(doc), []).append(doc)

    _wipe(OUT)
    for doc in docs:
        try:
            text = (KB_ROOT / doc).read_text()
        except OSError:
            continue
        topics = sorted(doc_topics.get(doc, set()))
        body = _body_without_frontmatter(text)

        # Group tag drives Obsidian's color groups; topic tags feed the tag pane.
        tags = [f"group/{_group(doc)}"] + [_sanitize_tag(t) for t in topics]
        fm = ["---", "tags: [" + ", ".join(tags) + "]", f"source: {doc}", "---"]
        head = "\n".join(fm)
        marker = "<!-- AUTO-GENERATED by kb-obsidian.py — edits overwritten; curate the real KB -->"

        # Graph stays hub-and-spoke (like graphify's community stars), not a hairball:
        # the group hub is the backbone, and only STRONG doc-doc links become edges.
        # Weak single-topic overlaps would connect nearly everything — those are
        # navigable via the hub / tag pane, not as graph edges.
        grp = _group(doc)
        related = [f"- [[_group-{grp}]] — (group)"]  # tie node to its group hub
        strong = sorted(((nb, sh) for nb, sh in topic_n.get(doc, {}).items()
                         if len(sh) >= MIN_SHARED_TOPICS),
                        key=lambda kv: (-len(kv[1]), kv[0]))[:MAX_TOPIC_LINKS]
        linked = {nb for nb, _ in strong}
        for nb, shared in strong:
            related.append(f"- {_wikilink(nb, stem_counts)} — {', '.join(sorted(shared))}")
        for nb in sorted(ast_n.get(doc, set()))[:MAX_AST_LINKS]:
            if nb not in linked:
                related.append(f"- {_wikilink(nb, stem_counts)} — (code)")
        rel_section = "\n\n## Related\n" + "\n".join(related)
        # Inline tags too — Obsidian's graph color groups read these most reliably.
        inline = " ".join(f"#{t}" for t in tags)

        dest = OUT / doc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"{head}\n{marker}\n\n{body.rstrip()}{rel_section}\n\n{inline}\n")

    _write_group_hubs(OUT, groups, stem_counts, topic_n, ast_n)
    _write_graph_config(OUT, list(groups))
    _mermaid_overview(OUT)

    # Record enabled + path so the post-commit hook regenerates this vault.
    try:
        cfgp = KB_ROOT / ".kb" / "config.json"
        cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}
        cfg.setdefault("obsidian", {})
        cfg["obsidian"]["enabled"] = True
        cfg["obsidian"]["path"] = os.path.relpath(OUT, lib.REPO_ROOT)
        cfgp.parent.mkdir(parents=True, exist_ok=True)
        cfgp.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass

    print(f"Obsidian vault → {OUT}  ({len(docs)} docs, {len(groups)} groups). "
          f"Open that folder as a vault.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
