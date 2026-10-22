#!/usr/bin/env python3
"""PreToolUse guard for KB-capture forks: allow Read/Glob/Grep and Write under the given directories, deny the rest.

  python3 kb-capture-guard.py <allowed_dir> [<allowed_dir> ...]     (PreToolUse payload on stdin)
Sandboxing by hook instead of tool flags keeps the fork's tool list, and so its prompt cache, identical
to the parent session's.
"""
import json
import sys
from pathlib import Path

READ_ONLY = {"Read", "Glob", "Grep"}


def decide(payload: dict, allowed: list[Path]) -> str:
    tool = payload.get("tool_name")
    if tool in READ_ONLY:
        return "allow"
    if tool == "Write":
        target = Path(str((payload.get("tool_input") or {}).get("file_path", ""))).resolve()
        return "allow" if any(target.is_relative_to(d.resolve()) for d in allowed) else "deny"
    return "deny"


def main() -> None:
    try:
        decision = decide(json.load(sys.stdin), [Path(a) for a in sys.argv[1:]])
    except Exception:  # noqa: BLE001 — a crashing guard would let the tool run; fail closed
        decision = "deny"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision,
        "permissionDecisionReason": "capture fork: only Read/Glob/Grep and Write into its inbox"}}))


if __name__ == "__main__":
    main()
