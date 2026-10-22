#!/usr/bin/env python3
"""PostToolUse Read hook: inject related KB files into context after a KB doc is read.

Reads the tool event from stdin (PostToolUse format), extracts the read file path,
and — only for files under the project's .claude/knowledge/ — emits the shared-topic
related-files graph as additionalContext. Silent (exit 0, no output) for any non-KB
file, so it's cheap to run on every Read.

Manual/test mode: pass a file path as argv[1] (and optionally kb_root as argv[2]).
"""
import json
import os
import sys
from pathlib import Path


MAX_SUGGEST = 4
MAX_HOP = 5
DESC_CHARS = 100


def _payload_from_stdin() -> dict:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return {}
    return event if isinstance(event, dict) else {}


def _seen_file(session_id: str) -> Path:
    return Path.home() / ".claude" / "kb-gate" / f"related-{session_id}.json"


def _short(desc: str) -> str:
    first = desc.split(". ")[0].strip()
    return first if len(first) <= DESC_CHARS else first[:DESC_CHARS - 1].rstrip() + "…"


def main() -> None:
    payload = {} if len(sys.argv) > 1 else _payload_from_stdin()
    file_path = sys.argv[1] if len(sys.argv) > 1 else (payload.get("tool_input") or {}).get("file_path")
    session_id = payload.get("session_id")
    if not file_path:
        sys.exit(0)

    # Fast skip BEFORE importing kb_graph (which runs a git subprocess at import):
    # only KB markdown files can have related docs. A cheap string check keeps the
    # global hook near-free on every other Read, in any repo.
    if ".claude/knowledge/" not in file_path or not file_path.endswith(".md"):
        sys.exit(0)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kb_config
    owner = kb_config.kb_of_file(file_path)
    if owner and not os.getenv("KB_ROOT"):
        os.environ["KB_ROOT"] = str(owner)
    import kb_graph

    import kb_config
    kb_root = Path(sys.argv[2]) if len(sys.argv) > 2 else kb_graph._KB_ROOT
    if not kb_config.enabled("related_docs", Path(kb_root)):
        sys.exit(0)

    try:
        rel = str(Path(file_path).resolve().relative_to(Path(kb_root).resolve()))
    except (ValueError, OSError):
        sys.exit(0)  # not a KB file

    doc_topics = kb_graph._load_doc_topics()
    my = doc_topics.get(rel)
    if not my:
        sys.exit(0)

    # Hub topics are categories, not real links — exclude them so suggestions stay sharp.
    counts: dict[str, int] = {}
    for ts in doc_topics.values():
        for t in ts:
            counts[t] = counts.get(t, 0) + 1
    hubs = {t for t, c in counts.items() if c > kb_graph.hub_threshold(len(doc_topics))}
    my_folder = rel.rsplit("/", 1)[0] if "/" in rel else ""

    def _candidate(other: str) -> bool:
        if other == rel:
            return False
        parts = other.split("/")
        if any(d in kb_graph._EXCLUDE_DIRS for d in parts):
            return False
        if my_folder and other.rsplit("/", 1)[0] == my_folder:
            return False  # same folder already visible from its index
        return True

    seen_file = _seen_file(session_id) if session_id else None
    seen: set[str] = set(json.loads(seen_file.read_text())) if seen_file and seen_file.exists() else set()
    seen.add(rel)

    direct = []
    for other, ot in doc_topics.items():
        if not _candidate(other) or other in seen:
            continue
        shared = (my & ot) - hubs
        if shared:
            direct.append((other, len(shared), sorted(shared)))
    direct.sort(key=lambda x: (-x[1], x[0]))
    direct = direct[:MAX_SUGGEST]

    descriptions = kb_graph.doc_descriptions()
    try:
        hops = kb_graph.kb_config().get("related_hops", 2)
    except Exception:
        hops = 2

    lines = ["[KB graph] Related docs not yet seen this session — read the ones that bear on the task "
             "(paths: ~/.claude/kb/scripts/resolve-file.py <name>):"]
    listed = {rel} | {d for d, _, _ in direct}
    for doc, _, shared in direct:
        stem = Path(doc).stem
        desc = _short(descriptions.get(doc, ""))
        tag = f"  ({', '.join(shared[:3])})"
        lines.append(f"  {stem} — {desc}{tag}" if desc else f"  {stem}{tag}")

    # 1-hop (friends-of-friends), bare names, only when configured (related_hops >= 2).
    if hops >= 2:
        hop: set[str] = set()
        direct_topics = {t for _, _, sh in direct for t in sh}
        for other, ot in doc_topics.items():
            if other in listed or other in seen or not _candidate(other):
                continue
            if (ot & direct_topics) - hubs:
                hop.add(other)
        if hop:
            hop_docs = sorted(hop)[:MAX_HOP]
            listed |= set(hop_docs)
            lines.append(f"  +1-hop: {', '.join(Path(d).stem for d in hop_docs)}")

    if seen_file:
        seen_file.parent.mkdir(parents=True, exist_ok=True)
        seen_file.write_text(json.dumps(sorted(seen | listed)))
    if len(lines) == 1:
        sys.exit(0)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }))


if __name__ == "__main__":
    main()
