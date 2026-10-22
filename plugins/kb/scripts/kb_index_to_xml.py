#!/usr/bin/env python3
"""Convert .claude/knowledge/index.json to compact XML for session-start injection.

Defensive by design: the index is maintained by an AI and may be malformed,
have missing fields, or wrong types. We never raise — on any problem we emit
a best-effort result plus a <kb-index-warning> sibling so the session still
starts and the model can see what went wrong.

Usage: kb_index_to_xml.py <path-to-index.json>
Exit codes: 0 = ok, 1 = file missing, 2 = usage error. Parse/shape problems
still return 0 (we emit a degraded block rather than break the hook).
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path
from typing import Any


def attr(value: Any) -> str:
    return escape(str(value), quote=True)


def text(value: Any) -> str:
    return escape(str(value), quote=False)


def _topics_csv(raw: Any) -> str:
    if isinstance(raw, list):
        return ",".join(str(t).strip() for t in raw if t is not None and str(t).strip())
    if isinstance(raw, str):
        return raw.strip()
    return ""


def _desc(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip().replace("\n", " ")


def render(index: Any) -> tuple[str, list[str]]:
    """Return (xml, warnings). Never raises."""
    warnings: list[str] = []

    if not isinstance(index, dict):
        warnings.append(f"index.json root is {type(index).__name__}, expected object")
        index = {}

    purpose = _desc(index.get("description")) or "Knowledge base index"
    usage = (
        "AUTHORITATIVE source for this project's architecture, components, and design "
        "decisions — check this BEFORE auto-memory, code search, or exploration. "
        "Auto-memory captures user/project state (preferences, active work, recent "
        "decisions); it is NOT a substitute for the KB on technical questions and "
        "may be stale. Workflow: match the query topic to an <entry> and Read that "
        "file; for structure/relationship questions (what calls X, how A and B "
        "connect, a symbol's or doc's neighborhood) use the code_graph source "
        "(kb-query: explain/neighbors/path/query) instead of grep. Fall back to "
        "memory or code only if the KB is insufficient. Use the /kb:base "
        "skill to look up entries; KB content changes go through the inbox + clean, "
        "except small corrections, which may be edited in place."
    )

    entries = index.get("entries", {})
    if not isinstance(entries, dict):
        warnings.append(f"'entries' is {type(entries).__name__}, expected object")
        entries = {}

    folders: list[str] = []
    files: list[str] = []

    for key, meta in entries.items():
        if not isinstance(meta, dict):
            warnings.append(f"entry '{key}' is {type(meta).__name__}, skipped")
            continue
        folder = meta.get("folder")
        path = folder if isinstance(folder, str) and folder else str(key)
        topics = _topics_csv(meta.get("topics"))
        desc = _desc(meta.get("description"))
        line = (
            f'  <entry path="{attr(path)}" topics="{attr(topics)}">'
            f"{text(desc)}</entry>"
        )
        (folders if folder else files).append(line)

    refs: list[str] = []
    supp = index.get("supplementary_docs", {})
    if not isinstance(supp, dict):
        warnings.append(
            f"'supplementary_docs' is {type(supp).__name__}, expected object"
        )
        supp = {}
    for key, meta in supp.items():
        if not isinstance(meta, dict):
            warnings.append(f"supplementary '{key}' is {type(meta).__name__}, skipped")
            continue
        path = meta.get("file") or key
        refs.append(f'  <ref path="{attr(path)}">{text(_desc(meta.get("description")))}</ref>')

    sources: list[str] = []
    raw_sources = index.get("sources", {})
    if not isinstance(raw_sources, dict):
        warnings.append(f"'sources' is {type(raw_sources).__name__}, expected object")
        raw_sources = {}
    for name, meta in raw_sources.items():
        if not isinstance(meta, dict):
            warnings.append(f"source '{name}' is {type(meta).__name__}, skipped")
            continue
        tool = _desc(meta.get("tool"))
        body = f"{_desc(meta.get('use_for'))} {_desc(meta.get('info'))}".strip()
        sources.append(
            f'  <source name="{attr(name)}" tool="{attr(tool)}">{text(body)}</source>'
        )

    if not (folders or files or refs or sources):
        known = {"description", "entries", "supplementary_docs", "sources"}
        other_keys = sorted(k for k in index if k not in known)
        warnings.append(
            "index rendered zero entries — expected non-empty 'entries' object; "
            f"unrecognized top-level keys: {other_keys or 'none'}"
        )

    parts = [
        f'<kb-index purpose="{attr(purpose)}" usage="{attr(usage)}">',
        *folders,
        *files,
        *refs,
        *sources,
        "</kb-index>",
    ]
    if warnings:
        parts.append("<kb-index-warning>")
        for w in warnings:
            parts.append(f"  - {text(w)}")
        parts.append("</kb-index-warning>")
    return "\n".join(parts), warnings


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(
            f'<kb-index-warning>index.json not found at {text(path)}</kb-index-warning>'
        )
        return 1

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"<kb-index-warning>read failed: {text(exc)}</kb-index-warning>")
        return 1

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(
            f"<kb-index-warning>index.json is not valid JSON "
            f"({text(exc.msg)} at line {exc.lineno} col {exc.colno}); "
            f"raw contents follow</kb-index-warning>"
        )
        print("<kb-index-raw>")
        print(text(raw))
        print("</kb-index-raw>")
        return 0

    xml, _warnings = render(data)
    print(xml)
    return 0


if __name__ == "__main__":
    sys.exit(main())
