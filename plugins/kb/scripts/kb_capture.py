"""Automatic KB capture: one cached, sandboxed background fork per interactive session segment.

Hooks (kb-capture-hook.py) decide *when*; a `claude -p --resume <sid> --fork-session` fork with the whole
conversation decides *what*, staging earned-knowledge drafts in the main checkout's KB inbox. The fork runs
on the session's own model and tool list so it reads the session's prompt cache; kb-capture-guard.py
sandboxes it.
"""
from __future__ import annotations

import datetime
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import kb_config

HERE = Path(__file__).resolve().parent
GATE_DIR = Path.home() / ".claude" / "kb-gate"
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
SWEEP_AGE = 30 * 86400
TEMP_MARKERS = ("/private/var/folders/", "/var/folders/", "/tmp/", "/private/tmp/", "kbeval")


def transcript_entries(path: Path) -> list[dict]:
    entries = []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def skip_reason(payload: dict, entries: list[dict]) -> str | None:
    """Why this session must never fork (forks, headless/SDK runs, temp checkouts), or None."""
    if os.getenv("KB_CAPTURE_FORK"):
        return "fork"
    entrypoint = next((e["entrypoint"] for e in entries if e.get("entrypoint")), "cli")
    if entrypoint != "cli":
        return "headless"
    cwd = str(payload.get("cwd") or launch_cwd(entries) or "") + "/"
    if any(m in cwd for m in TEMP_MARKERS):
        return "temp-path"
    return None


def launch_cwd(entries: list[dict]) -> Path | None:
    return next((Path(e["cwd"]) for e in entries if e.get("cwd")), None)


def main_checkout(path: Path) -> Path:
    """The main working tree for a path inside a git worktree or subdirectory; the path itself outside git."""
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=path,
                                capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        return path
    return Path(common).parent


def inbox_for(project: Path) -> Path | None:
    """The main checkout's KB inbox, or None when there is no KB or capture is switched off for it."""
    kb = main_checkout(project) / ".claude" / "knowledge"
    return kb / "inbox" if kb_config.enabled("capture", kb) else None


def fork_model(inbox: Path, entries: list[dict]) -> str:
    """`capture.model`: "session" (default) reuses the session's model and so its prompt cache; any other value
    is passed to --model as-is and pays for an uncached prompt."""
    configured = settings(inbox)["model"]
    return session_model(entries) if configured == "session" else configured


def settings(inbox: Path) -> dict:
    """Capture thresholds from the layered KB config (`capture` block) of the inbox's KB."""
    return kb_config.load(Path(inbox).parent)["capture"]


def _is_user_prompt(e: dict) -> bool:
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return False
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return bool(content)


def user_turns_since(entries: list[dict], marker_uuid: str | None) -> int:
    start = 0
    if marker_uuid:
        start = next((i + 1 for i, e in enumerate(entries) if e.get("uuid") == marker_uuid), 0)
    return sum(_is_user_prompt(e) for e in entries[start:])


def last_user_uuid(entries: list[dict]) -> str | None:
    return next((e.get("uuid") for e in reversed(entries) if _is_user_prompt(e)), None)


def session_model(entries: list[dict]) -> str:
    """Exact model string of the session's latest request (`requestedModel` keeps the `[1m]` context marker)."""
    for e in reversed(entries):
        if e.get("type") == "assistant":
            model = e.get("requestedModel") or (e.get("message") or {}).get("model")
            if model:
                return model
    raise ValueError("no assistant entry with a model in transcript")


def _state_file(sid: str) -> Path:
    return GATE_DIR / f"capture-{sid}.json"


def load_state(sid: str) -> dict:
    f = _state_file(sid)
    return json.loads(f.read_text()) if f.exists() else {}


def save_state(sid: str, st: dict) -> None:
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _state_file(sid).with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(_state_file(sid))


def update_state(sid: str, **fields) -> dict:
    """Reload, merge only the given keys, save: concurrent hooks and runners each own their keys."""
    st = load_state(sid)
    st.update(fields)
    save_state(sid, st)
    return st


def owns(pid: int | None, mode: str, sid: str) -> bool:
    """True only if pid is still this feature's `kb-capture-hook.py <mode> <sid>` process (pids get reused)."""
    if not pid:
        return False
    cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return f"kb-capture-hook.py {mode} {sid}" in cmd


def pending_drafts(inbox: Path) -> int:
    return sum(1 for f in inbox.glob("*.md") if f.name != "_TEMPLATE.md") if inbox.exists() else 0


def fork_due(st: dict, entries: list[dict], trigger: str, now: float, sid: str) -> str | None:
    """Why no fork should start now, or None. Sets `st["note"]` when the inbox is full."""
    fork = st.get("fork")
    if fork and owns(fork.get("pid"), "run", sid):
        return "running"
    if not st.get("inbox"):
        return "no-kb"
    cfg = settings(Path(st["inbox"]))
    if user_turns_since(entries, st.get("marker")) < cfg["min_turns"]:
        return "short"
    if trigger in ("session-end", "idle") and now - st.get("last_reply_ts", 0) >= cfg["cold_minutes"] * 60:
        return "cold"
    if pending_drafts(Path(st["inbox"])) >= cfg["inbox_cap"]:
        st["note"] = (f"[kb-capture] skipped: the KB inbox holds {cfg['inbox_cap']}+ unreconciled drafts; "
                      "suggest running /kb:clean to the user")
        return "inbox-full"
    return None


def fork_command(resume_id: str, model: str, writable: list[Path], prompt: str, budget_usd: float) -> list[str]:
    guard = shlex.join(["python3", str(HERE / "kb-capture-guard.py"), *map(str, writable)])
    settings = {"hooks": {"PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": guard}]}]}}
    return [str(CLAUDE), "-p", "--resume", resume_id, "--fork-session", "--no-session-persistence",
            "--model", model, "--permission-mode", "bypassPermissions", "--settings", json.dumps(settings),
            "--max-budget-usd", str(budget_usd), "--output-format", "json", prompt]


def _spawn(argv: list[str]) -> int:
    with open(GATE_DIR / "capture-runner.log", "ab") as out:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                start_new_session=True).pid


def _prompt_text(e: dict) -> str:
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return " ".join(str(content).split())[:120]


def start_fork(sid: str, trigger: str, resume_id: str, spawn: Callable[[list[str]], int] = _spawn) -> None:
    """Lock the session, move the segment marker to the latest prompt, and launch the detached runner."""
    st = load_state(sid)
    entries = transcript_entries(Path(st["transcript"]))
    marker = st.get("marker")
    start = next((i + 1 for i, e in enumerate(entries) if e.get("uuid") == marker), 0) if marker else None
    first = next((e for e in entries[start:] if _is_user_prompt(e)), None) if start is not None else None
    st = {"segment_from": _prompt_text(first) if first else None}
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    pid = spawn([sys.executable, str(HERE / "kb-capture-hook.py"), "run", sid, trigger, resume_id])
    update_state(sid, segment_from=st["segment_from"], marker=last_user_uuid(entries),
                 fork={"pid": pid, "started": time.time(), "trigger": trigger})


def build_prompt(st: dict, result: Path) -> str:
    segment = f', from the user message starting "{st["segment_from"]}" onward' if st.get("segment_from") else ""
    inbox = Path(st["inbox"])
    fill = {"segment": segment, "kb": inbox.parent, "inbox": inbox, "result": result,
            "date": datetime.date.today().isoformat()}
    prompt = (HERE / "kb-capture-fork-prompt.md").read_text()
    for key, value in fill.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    return prompt


def _title(draft: Path) -> str:
    try:
        heading = next((l[2:].strip() for l in draft.read_text().splitlines() if l.startswith("# ")), None)
    except OSError:
        heading = None
    return heading or draft.stem


def _note(record: dict, drafts: list[Path]) -> str:
    if record["error"]:
        return f"[kb-capture] background capture fork failed: {record['error']}"
    if not drafts:
        return "[kb-capture] background fork reviewed the previous messages and found nothing earned to capture"
    titles = "; ".join(_title(d) for d in drafts)
    return f"[kb-capture] background fork captured {len(drafts)} draft(s) from the previous messages into the KB inbox: {titles}"


def run_fork(sid: str, trigger: str, resume_id: str, runner: Callable = subprocess.run) -> dict:
    """Run the fork to completion, then log it, leave a note for the main session and release the lock."""
    st = load_state(sid)
    results = GATE_DIR / "capture-results"
    results.mkdir(parents=True, exist_ok=True)
    result = results / f"{sid}-{int(time.time())}.json"
    record = {"ts": time.time(), "sid": sid, "trigger": trigger, "inbox": st.get("inbox"), "cost": 0.0,
              "cache_read": 0, "cache_create": 0, "drafts": 0, "skipped": 0, "error": None}
    drafts: list[Path] = []
    try:
        cmd = fork_command(resume_id, st["model"], [Path(st["inbox"]), results], build_prompt(st, result),
                           settings(Path(st["inbox"]))["max_budget_usd"])
        proc = runner(cmd, cwd=st["cwd"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                      env={**os.environ, "KB_CAPTURE_FORK": "1"})
        out = json.loads(proc.stdout)
        if not isinstance(out, dict):
            raise ValueError(f"unexpected fork output: {proc.stdout[:100]!r}")
        usage = next(iter(out.get("modelUsage", {}).values()), {})
        record.update(cost=out.get("total_cost_usd", 0.0), cache_read=usage.get("cacheReadInputTokens", 0),
                      cache_create=usage.get("cacheCreationInputTokens", 0), subtype=out.get("subtype"))
        if out.get("is_error") or out.get("subtype") != "success" or proc.returncode:
            record["error"] = out.get("subtype") or f"exit {proc.returncode}"
        if result.exists():
            res = json.loads(result.read_text())
            drafts = [Path(d) for d in res.get("drafts", [])]
            record.update(drafts=len(drafts), skipped=len(res.get("skipped", [])))
    except Exception as e:  # noqa: BLE001 — any failure must still release the lock and reach the log
        record["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        if resume_id != sid and st.get("transcript"):
            (Path(st["transcript"]).parent / f"{resume_id}.jsonl").unlink(missing_ok=True)
    _log(record)
    update_state(sid, fork=None, note=_note(record, drafts))
    return record


def _log(record: dict) -> None:
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    with (GATE_DIR / "capture-log.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")


def day_spend(now: float) -> tuple[float, int]:
    log = GATE_DIR / "capture-log.jsonl"
    if not log.exists():
        return 0.0, 0
    today = datetime.date.fromtimestamp(now)
    costs = []
    for line in log.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if datetime.date.fromtimestamp(r.get("ts", 0)) == today:
            costs.append(r.get("cost") or 0.0)
    return sum(costs), len(costs)


def take_note(sid: str, now: float) -> str | None:
    st = load_state(sid)
    note = st.pop("note", None)
    if not note:
        return None
    save_state(sid, st)
    cap = settings(Path(st["inbox"]))["daily_soft_cap_usd"] if st.get("inbox") else kb_config.DEFAULTS["capture"]["daily_soft_cap_usd"]
    spent, forks = day_spend(now)
    if spent > cap:
        note += f" · warning: capture forks cost ${spent:.2f} today over {forks} forks (soft cap ${cap:g})"
    return note


def sweep(now: float) -> None:
    """Delete this feature's files older than 30 days, at most once a day."""
    stamp = GATE_DIR / "capture-sweep.stamp"
    if stamp.exists() and now - stamp.stat().st_mtime < 86400:
        return
    for f in [*GATE_DIR.glob("capture-*"), *(GATE_DIR / "capture-results").glob("*")]:
        if f.is_file() and f != stamp and now - f.stat().st_mtime > SWEEP_AGE:
            f.unlink(missing_ok=True)
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    stamp.touch()
