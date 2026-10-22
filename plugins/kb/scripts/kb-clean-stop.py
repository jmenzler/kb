#!/usr/bin/env python3
"""Stop hook: surface an armed KB-clean ask once, after the session's first message.

`kb-clean-due.py` (SessionStart) arms `.kb/pending-clean-ask.json` when a clean is due. This
hook delivers it: on the first stop of a session it emits a `block` decision whose `reason`
instructs the assistant to ask the user about running `/kb:clean`, then records
the session so it never re-fires this session (the "only the first message" guarantee).

FAIL-SILENT — never blocks a stop on error. Loop-safe via two guards:
  - `stop_hook_active` in the payload (we are already in a stop-hook continuation) -> exit.
  - session_id already in the pending file's `fired_sessions` -> exit.

Stamps `last-clean-suggested` only here, on actual delivery — so the cooldown reflects when
the user was really asked, not when the condition was merely detected.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    if os.getenv("KB_CAPTURE_FORK"):  # background capture forks must not be gated or nudged
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    # Already continuing because of a stop hook — don't re-arm into a loop.
    if payload.get("stop_hook_active"):
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kb_config
    root = kb_config.session_kb_root(payload)
    if not kb_config.enabled("clean_nudge", root):
        return 0
    kbdir = root / ".kb"
    pending_path = kbdir / "pending-clean-ask.json"
    if not pending_path.exists():
        return 0

    try:
        pending = json.loads(pending_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0

    # No session_id → can't track that we fired, so don't (a synthetic key would coalesce
    # distinct untracked sessions and silently skip all but the first).
    sid = payload.get("session_id")
    if not sid:
        return 0
    fired = pending.get("fired_sessions", [])
    if sid in fired:
        return 0

    message = pending.get("message")
    if not message:
        return 0

    # Persist that we fired BEFORE emitting the block — if the write fails we must not
    # fire, or the unrecorded session re-fires on its next stop.
    fired.append(sid)
    pending["fired_sessions"] = fired
    try:
        tmp = pending_path.parent / (pending_path.name + ".tmp")
        tmp.write_text(json.dumps(pending))
        tmp.replace(pending_path)
    except OSError:
        return 0
    try:
        (kbdir / "last-clean-suggested").write_text(str(int(time.time())))
    except OSError:
        pass

    print(json.dumps({"decision": "block", "reason": message}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never block a stop
        sys.exit(0)
