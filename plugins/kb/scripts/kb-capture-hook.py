#!/usr/bin/env python3
"""Hook entry for automatic KB capture (logic lives in kb_capture.py).

  stop          Stop: record the session (transcript, cwd, inbox, model, last reply) and restart the idle timer
  session-end   SessionEnd: fork now if the segment is due and the cache is still warm
  precompact    PreCompact: fork from a copy of the transcript, before compaction rewrites it
  prompt        UserPromptSubmit: inject the last fork's one-line note into the main session
  idle <sid> <ts>             detached: after 45 min without a newer reply, fork
  run <sid> <trigger> <id>    detached: run the fork to completion
Never raises into Claude Code: errors go to ~/.claude/kb-gate/capture-log.jsonl.
"""
import json
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kb_capture  # noqa: E402


def _kill(pid: int | None, sid: str) -> None:
    if kb_capture.owns(pid, "idle", sid):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def _stop(sid: str, payload: dict, now: float) -> None:
    transcript = Path(payload["transcript_path"])
    if not transcript.exists():  # headless runs whose config dir was already removed
        return
    entries = kb_capture.transcript_entries(transcript)
    if kb_capture.skip_reason(payload, entries):
        return
    project = kb_capture.launch_cwd(entries) or Path(payload["cwd"])
    inbox = kb_capture.inbox_for(project)
    if inbox is None:
        return
    _kill(kb_capture.load_state(sid).get("idle_pid"), sid)
    idle_pid = kb_capture._spawn([sys.executable, str(Path(__file__).resolve()), "idle", sid, str(now)])
    kb_capture.update_state(sid, transcript=payload["transcript_path"], cwd=payload.get("cwd") or str(project),
                            inbox=str(inbox), model=kb_capture.fork_model(inbox, entries),
                            last_reply_ts=now, idle_pid=idle_pid)
    kb_capture.sweep(now)


def _maybe_fork(sid: str, trigger: str, now: float) -> None:
    st = kb_capture.load_state(sid)
    if not st.get("transcript"):
        return
    entries = kb_capture.transcript_entries(Path(st["transcript"]))
    reason = kb_capture.fork_due(st, entries, trigger, now, sid)
    if reason:
        if reason != "short":
            kb_capture._log({"ts": now, "sid": sid, "trigger": trigger, "skipped_fork": reason, "error": None})
        if st.get("note"):
            kb_capture.update_state(sid, note=st["note"])
        return
    if trigger == "session-end":
        _kill(st.get("idle_pid"), sid)
    if trigger != "precompact":
        kb_capture.start_fork(sid, trigger, sid)
        return
    resume_id = str(uuid.uuid4())
    copy = Path(st["transcript"]).parent / f"{resume_id}.jsonl"
    shutil.copyfile(st["transcript"], copy)
    try:
        kb_capture.start_fork(sid, trigger, resume_id)
    except BaseException:
        copy.unlink(missing_ok=True)
        raise


def handle(mode: str, payload: dict, now: float) -> None:
    sid = payload.get("session_id")
    if mode == "stop":
        _stop(sid, payload, now)
    elif mode == "session-end":
        _maybe_fork(sid, "session-end", now)
    elif mode == "precompact":
        _maybe_fork(sid, "precompact", now)
    elif mode == "prompt":
        note = kb_capture.take_note(sid, now)
        if note:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": note}}))
    else:
        raise ValueError(f"unknown mode {mode!r}")


def idle(sid: str, ts: float, sleep=time.sleep, now=time.time) -> None:
    inbox = kb_capture.load_state(sid).get("inbox")
    if not inbox:
        return
    sleep(kb_capture.settings(Path(inbox))["idle_minutes"] * 60)
    if kb_capture.load_state(sid).get("last_reply_ts") != ts:
        return
    _maybe_fork(sid, "idle", now())


def main() -> int:
    if os.getenv("KB_CAPTURE_FORK"):
        return 0
    try:
        mode = sys.argv[1]
        if mode == "idle":
            idle(sys.argv[2], float(sys.argv[3]))
        elif mode == "run":
            kb_capture.run_fork(*sys.argv[2:5])
        else:
            handle(mode, json.load(sys.stdin), time.time())
    except Exception as e:  # noqa: BLE001 — a hook must never break the user's session
        kb_capture._log({"ts": time.time(), "mode": sys.argv[1:2], "error": f"{type(e).__name__}: {str(e)[:300]}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
