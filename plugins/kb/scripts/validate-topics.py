#!/usr/bin/env python3
"""PreToolUse hook: validate topic tags in KB index.json before write/edit.

Reads the tool event from stdin, extracts the file path, computes what the
file content WOULD be after the write/edit, and checks all topic tags against
the canonical topics.json registry.

Outputs PreToolUse hook format:
  - permissionDecision: "deny" + systemMessage on invalid topics
  - exit 0 (no output) on valid or non-KB-json files
"""

import json
import sys
from pathlib import Path


def load_registry(registry_path: str) -> set[str]:
    with open(registry_path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return set(data)
    if isinstance(data, dict) and "topics" in data:
        return set(data["topics"])
    return set()


def extract_topics(obj, path: str = "") -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        if "topics" in obj and isinstance(obj["topics"], list):
            for t in obj["topics"]:
                pairs.append((t, f"{path}.topics" if path else "topics"))
        for k, v in obj.items():
            pairs.extend(extract_topics(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            pairs.extend(extract_topics(v, f"{path}[{i}]"))
    return pairs


def compute_new_content(tool_input: dict) -> str | None:
    """Return the content the file WOULD have after this write/edit, or None if not computable."""
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".json") or ".claude/knowledge/" not in file_path:
        return None

    # Write: content is in tool_input directly
    if "content" in tool_input:
        return tool_input["content"]

    # Edit: apply old_string -> new_string on current file content
    if "old_string" in tool_input and "new_string" in tool_input:
        try:
            current = Path(file_path).read_text()
        except (FileNotFoundError, OSError):
            return None
        old = tool_input["old_string"]
        new = tool_input["new_string"]
        if old not in current:
            return None  # can't compute — let it through
        return current.replace(old, new, 1)

    return None


def _suggest_matches(invalid: list[tuple[str, str]], valid: set[str]) -> str:
    lines = []
    for topic, _ in invalid:
        matches = [v for v in valid if topic in v or v in topic]
        if matches:
            lines.append(f"  Did you mean: {', '.join(sorted(matches)[:5])}?")
        else:
            lines.append(f"  No close match for \"{topic}\" — consider adding it to topics.json.")
    return "\n".join(lines)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    tool_input = event.get("tool_input", {})
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kb_config
    kb_root = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        kb_config.kb_of_file(tool_input.get("file_path", "")) or Path.cwd() / ".claude" / "knowledge")
    if not kb_config.enabled("topic_validation", kb_root):
        sys.exit(0)
    content = compute_new_content(tool_input)
    if content is None:
        sys.exit(0)  # not a KB json file, or can't compute — allow

    registry_path = kb_root / "topics.json"
    try:
        valid = load_registry(str(registry_path))
    except (FileNotFoundError, json.JSONDecodeError):
        sys.exit(0)

    if not valid:
        sys.exit(0)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        sys.exit(0)  # can't parse JSON — let it through, it'll fail on its own

    all_topics = extract_topics(data)
    invalid = [(t, p) for t, p in all_topics if t not in valid]

    if not invalid:
        sys.exit(0)

    file_path = tool_input.get("file_path", "unknown")
    suggestions = _suggest_matches(invalid, valid)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny"
        },
        "systemMessage": (
            f"TOPIC VALIDATION FAILED for {file_path}.\n"
            f"Invalid tags: {', '.join(t for t, _ in invalid)}.\n"
            f"{suggestions}\n"
            f"DECISION REQUIRED: Either (1) replace each invalid tag with a close match "
            f"from the valid topics list, or (2) if the concept genuinely needs a "
            f"new topic, add it to {kb_root}/topics.json FIRST, then re-apply it here. "
            f"Do NOT proceed with invalid topic tags."
        )
    }))


if __name__ == "__main__":
    main()
