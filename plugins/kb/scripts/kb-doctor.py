#!/usr/bin/env python3
"""KB doctor — staleness + integrity report for a project knowledge base.

Checks (read-only, never mutates):
  1. Orphaned docs   — .md files with no topic tag in any index.json
  2. Dangling folder — root entry has `folder` but the dir/index.json is missing
  3. Dangling supp   — supplementary_docs `file` path does not exist
  4. Dead code refs  — `path/to/file.ext` cited in KB prose no longer exists on disk
  5. Topic drift     — index topics absent from topics.json; topics.json entries unused

Usage: kb-doctor.py [kb_root]   (default: git-resolved .claude/knowledge)
Always exits 0 — a report, not a gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_LINES = 400  # KB docs are atomic topic files; longer → split candidate

# argv override must be set before importing kb_graph (it resolves KB_ROOT at import).
if len(sys.argv) > 1:
    os.environ["KB_ROOT"] = str(Path(sys.argv[1]).resolve())

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_graph  # noqa: E402
import kb_ast_lib as lib  # noqa: E402

KB_ROOT = kb_graph._KB_ROOT
REPO_ROOT = KB_ROOT.parent.parent  # .claude/knowledge -> repo root

CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".rb",
            ".sql", ".sh", ".toml", ".yaml", ".yml", ".cfg", ".ini"}
# Backtick-wrapped tokens that look like a relative file path.
PATH_RE = re.compile(r"`([A-Za-z0-9_][\w./-]*\.[A-Za-z0-9]+)`")


def _iter_index_files() -> list[Path]:
    return [p for p in KB_ROOT.rglob("index.json")
            if not kb_graph.is_excluded(str(p.relative_to(KB_ROOT)))]


def _all_declared_topics() -> set[str]:
    topics: set[str] = set()
    for idx in _iter_index_files():
        try:
            data = json.loads(idx.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for collection in ("entries", "files"):
            for entry in (data.get(collection, {}) or {}).values():
                if isinstance(entry, dict):
                    topics.update(t for t in entry.get("topics", []) if isinstance(t, str))
    return topics


def check_dangling_folders() -> list[str]:
    """Folder entries at any depth whose directory or index.json is missing."""
    if not (KB_ROOT / "index.json").exists():
        return ["root index.json missing or invalid"]
    out = []
    for declaring, key, folder_prefix, _entry in kb_graph.iter_folder_entries():
        where = declaring or ""
        folder = KB_ROOT / folder_prefix
        if not folder.is_dir():
            out.append(f"entry '{where}{key}' \u2192 folder '{folder_prefix}' does not exist")
        elif not (folder / "index.json").exists():
            out.append(f"folder '{folder_prefix}' has no index.json")
    return out


def check_index_points_to_real_files() -> list[str]:
    """Every file an index.json lists must exist on disk (routing → dead file)."""
    out = []
    # Root entries that are files (no `folder` key).
    try:
        root = json.loads((KB_ROOT / "index.json").read_text())
    except (OSError, json.JSONDecodeError):
        return ["root index.json missing or invalid"]
    for key, entry in (root.get("entries", {}) or {}).items():
        if isinstance(entry, dict) and "folder" not in entry and key.endswith(".md"):
            if not (KB_ROOT / key).exists():
                out.append(f"index.json lists '{key}' — not on disk")
    # Folder index `files` entries.
    for idx in KB_ROOT.rglob("index.json"):
        if idx == KB_ROOT / "index.json" or kb_graph.is_excluded(str(idx.relative_to(KB_ROOT))):
            continue
        try:
            data = json.loads(idx.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        folder = idx.parent
        for fname in (data.get("files", {}) or {}):
            if not (folder / fname).exists():
                out.append(f"{idx.relative_to(KB_ROOT)} lists '{fname}' — not on disk")
    return out


def check_dangling_supp() -> list[str]:
    try:
        data = json.loads((KB_ROOT / "index.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for key, entry in (data.get("supplementary_docs", {}) or {}).items():
        if isinstance(entry, dict):
            ref = entry.get("file")
            if ref and not (KB_ROOT / ref).resolve().exists():
                out.append(f"supplementary '{key}' → '{ref}' does not exist")
    return out


def _repo_basenames() -> dict[str, list[str]] | None:
    """basename → [repo-relative paths]. Walks from project root via `fd`
    (fast, honors .gitignore), falling back to os.walk. None if nothing found."""
    paths: list[str] = []
    try:
        out = subprocess.check_output(
            ["fd", "--type", "f", "--exclude", "graphify-out", ".", str(REPO_ROOT)],
            text=True, stderr=subprocess.DEVNULL,
        )
        paths = out.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "graphify-out", ".mypy_cache"}
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            paths.extend(str(Path(dirpath) / f) for f in filenames)

    by_base: dict[str, list[str]] = {}
    root = REPO_ROOT.resolve()
    for p in paths:
        p = p.strip()
        if not p:
            continue
        try:
            rel = str(Path(p).resolve().relative_to(root))
        except ValueError:
            rel = p
        by_base.setdefault(Path(p).name, []).append(rel)
    return by_base or None


def check_code_refs() -> tuple[list[str], list[str]]:
    """Returns (dead, moved). A cited `path/to/x.ext` whose exact path is gone:
    if its basename exists elsewhere under the project → moved/shortform (path
    needs updating); if the basename exists nowhere → dead (file deleted)."""
    by_base = _repo_basenames()
    dead: dict[str, str] = {}   # ref -> citing doc
    moved: dict[str, tuple[list[str], str]] = {}  # ref -> (candidate paths, citing doc)
    for md in KB_ROOT.rglob("*.md"):
        if kb_graph.is_excluded(str(md.relative_to(KB_ROOT))):
            continue
        try:
            text = md.read_text()
        except OSError:
            continue
        rel_doc = str(md.relative_to(KB_ROOT))
        for m in PATH_RE.finditer(text):
            ref = m.group(1)
            if "/" not in ref or Path(ref).suffix not in CODE_EXT:
                continue
            # Top segment must be a real top-level dir, else it's prose shorthand
            # ("risk/checks.py") or an external-repo path — not ours to verify.
            if not (REPO_ROOT / ref.split("/", 1)[0]).is_dir():
                continue
            if (REPO_ROOT / ref).exists() or (KB_ROOT / ref).exists():
                continue
            if ref in dead or ref in moved:
                continue
            hits = by_base.get(Path(ref).name, []) if by_base else []
            if hits:
                moved[ref] = (hits, rel_doc)
            else:
                dead[ref] = rel_doc
    dead_lines = [f"{r}  (cited in {d})" for r, d in sorted(dead.items())]
    moved_lines = []
    for r, (hits, d) in sorted(moved.items()):
        if len(hits) == 1:
            moved_lines.append(f"{r} → {hits[0]}  (cited in {d})")
        else:
            # Ambiguous basename — multiple candidates. clean must NOT auto-apply; confirm.
            moved_lines.append(f"{r} → ? [{' | '.join(hits[:4])}]  AMBIGUOUS (cited in {d})")
    return dead_lines, moved_lines


def check_provenance() -> list[str]:
    """Flag KB docs whose declared `sources:` paths no longer exist on disk."""
    out: list[str] = []
    for md in KB_ROOT.rglob("*.md"):
        if kb_graph.is_excluded(str(md.relative_to(KB_ROOT))):
            continue
        try:
            srcs = lib.frontmatter_sources(md.read_text())
        except OSError:
            continue
        if not srcs:
            continue
        rel_doc = md.relative_to(KB_ROOT)
        for ref in srcs:
            if not (REPO_ROOT / ref).exists() and not (KB_ROOT / ref).exists():
                out.append(f"{rel_doc}: source '{ref}' gone")
    return out


def check_long_files() -> list[str]:
    sized: list[tuple[int, str]] = []
    for md in KB_ROOT.rglob("*.md"):
        if kb_graph.is_excluded(str(md.relative_to(KB_ROOT))):
            continue
        try:
            n = md.read_text().count("\n") + 1
        except OSError:
            continue
        if n > MAX_LINES:
            sized.append((n, str(md.relative_to(KB_ROOT))))
    return [f"{path}  ({n} lines)" for n, path in sorted(sized, reverse=True)]


def check_topic_drift() -> tuple[list[str], list[str]]:
    try:
        valid = set(json.loads((KB_ROOT / "topics.json").read_text()))
    except (OSError, json.JSONDecodeError):
        return (["topics.json missing or invalid"], [])
    declared = _all_declared_topics()
    invalid = sorted(declared - valid)   # used in an index but not registered
    unused = sorted(valid - declared)    # registered but never applied
    return invalid, unused


def check_folder_exclusions() -> list[str]:
    """Folder descriptions that never say what they EXCLUDE, or that point at a path.

    The exclusion half is what collapses two plausible folders into one — a description
    listing only what a folder holds leaves every neighbouring question ambiguous. And an
    exclusion naming a path ("NOT measurements (findings/)") couples every folder to every
    other folder's name: rename one and the pointer misroutes more confidently than no
    pointer at all. Name WHAT is excluded, in the vocabulary its owning folder uses.
    Declaring a child of this same folder is containment, not a cross-reference, so it is
    allowed. See STYLE.md § Index descriptions.
    """
    out: list[str] = []
    for _declaring, key, folder_prefix, entry in kb_graph.iter_folder_entries():
        desc = entry.get("description", "") or ""
        name = folder_prefix.rstrip("/") or key
        if "NOT " not in desc:
            out.append(f"{name}  description states no exclusion (no 'NOT ...' clause)")
        children: set[str] = set()
        idx = KB_ROOT / folder_prefix / "index.json"
        if idx.exists():
            try:
                data = json.loads(idx.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
            children = {(c.get("folder") or "").strip("/").split("/")[-1]
                        for c in (data.get("entries", {}) or {}).values()
                        if isinstance(c, dict)}
        for ref in re.findall(r"\(([a-z0-9-]+(?:/[a-z0-9-]+)*)/\)", desc):
            if ref.split("/")[-1] not in children:
                out.append(f"{name}  exclusion points at a path '{ref}/' — name what, not where")
    return out


def check_folder_tag_repeats() -> list[str]:
    """File-level topics that just repeat a containing folder's categorical tag.

    Inherited anyway, so the repeat adds no routing — it only names the doc's region a
    second time and manufactures file-level edges between docs that merely share a
    folder. Checked against every ancestor folder, since all of them are inherited.
    """
    out: list[str] = []
    for doc, entry, ancestors in kb_graph._iter_docs():
        if not ancestors:
            continue
        repeats = sorted(set(entry.get("topics", [])) & kb_graph._ancestor_topics(ancestors))
        if repeats:
            out.append(f"{doc}  repeats folder tag(s): {', '.join(repeats)}")
    return out


def _section(title: str, items: list[str], ok: str) -> tuple[str, int]:
    if not items:
        return f"✓ {title}: {ok}", 0
    lines = [f"✗ {title}: {len(items)} issue(s)"]
    lines += [f"    {i}" for i in items]
    return "\n".join(lines), len(items)


def main() -> int:
    if not (KB_ROOT / "index.json").exists():
        print(f"No KB at {KB_ROOT}")
        return 0

    orphan_report = kb_graph.check()
    orphans = [] if orphan_report.startswith("OK") else orphan_report.split("\n")[1:]
    invalid, unused = check_topic_drift()
    dead, moved = check_code_refs()

    blocks = [
        _section("Orphaned docs", [o.strip() for o in orphans], "all docs tagged"),
        _section("Dangling folders", check_dangling_folders(), "all folder refs resolve"),
        _section("Index points to missing files", check_index_points_to_real_files(), "all indexed files exist"),
        _section("Dangling supplementary docs", check_dangling_supp(), "all refs resolve"),
        _section("Dead code refs (file gone)", dead, "none"),
        _section("Stale code refs (file moved/shortform)", moved, "none"),
        _section("Broken provenance (sources: path gone)", check_provenance(), "all sources resolve"),
        _section("Long files (split candidates)", check_long_files(), f"none over {MAX_LINES} lines"),
        _section("Folder descriptions without an exclusion", check_folder_exclusions(), "every folder says what it excludes"),
        _section("File topics repeating their folder's tag", check_folder_tag_repeats(), "none"),
        _section("Topics used but not in topics.json", invalid, "none"),
        _section("Topics registered but unused", unused, "none"),
    ]

    print(f"KB doctor — {KB_ROOT}\n")
    total = 0
    for text, n in blocks:
        print(text)
        total += n
    print(f"\n{total} issue(s) across {len(blocks)} checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
