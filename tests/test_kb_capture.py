"""Automatic KB capture: guard sandbox, eligibility, placement, triggers, fork run, notes."""
import json
import os
import time
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"
GUARD = SCRIPTS / "kb-capture-guard.py"


def guard(allowed: Path, tool: str, **tool_input) -> str:
    out = subprocess.run([sys.executable, str(GUARD), str(allowed)], input=json.dumps(
        {"tool_name": tool, "tool_input": tool_input}), capture_output=True, text=True, check=True).stdout
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def test_guard_allows_reads(tmp_path):
    for tool in ("Read", "Glob", "Grep"):
        assert guard(tmp_path, tool, file_path="/etc/hosts") == "allow"


def test_guard_allows_write_inside_dir(tmp_path):
    assert guard(tmp_path, "Write", file_path=str(tmp_path / "inbox" / "a.md"), content="x") == "allow"


def test_guard_denies_write_outside(tmp_path):
    assert guard(tmp_path / "inbox", "Write", file_path=str(tmp_path / "other.md"), content="x") == "deny"


def test_guard_denies_prefix_trick(tmp_path):
    d = tmp_path / "inbox"
    assert guard(d, "Write", file_path=str(tmp_path / "inbox-evil" / "x.md"), content="x") == "deny"
    assert guard(d, "Write", file_path=str(d / ".." / "escape.md"), content="x") == "deny"


def test_guard_denies_bash_edit_agent(tmp_path):
    assert guard(tmp_path, "Bash", command="echo hi") == "deny"
    assert guard(tmp_path, "Edit", file_path=str(tmp_path / "a.md"), old_string="a", new_string="b") == "deny"
    assert guard(tmp_path, "Agent", prompt="do things") == "deny"


sys.path.insert(0, str(SCRIPTS))
import kb_capture  # noqa: E402


def user(uuid: str, text: str, **extra) -> dict:
    return {"type": "user", "uuid": uuid, "message": {"content": text}, **extra}


def assistant(uuid: str, text: str, model: str = "claude-opus-5-5[1m]") -> dict:
    return {"type": "assistant", "uuid": uuid, "requestedModel": model,
            "message": {"model": model.split("[")[0], "content": [{"type": "text", "text": text}]}}


def session(cwd: str = "/Users/x/repo", entrypoint: str = "cli") -> list[dict]:
    return [{"type": "mode"}, {**user("u1", "hi"), "cwd": cwd, "entrypoint": entrypoint}, assistant("a1", "hello")]


def test_skip_fork_env(monkeypatch):
    monkeypatch.setenv("KB_CAPTURE_FORK", "1")
    assert kb_capture.skip_reason({"cwd": "/Users/x/repo"}, session()) == "fork"


def test_skip_headless(monkeypatch):
    monkeypatch.delenv("KB_CAPTURE_FORK", raising=False)
    assert kb_capture.skip_reason({"cwd": "/Users/x/repo"}, session(entrypoint="sdk-cli")) == "headless"


def test_skip_temp_path(monkeypatch):
    monkeypatch.delenv("KB_CAPTURE_FORK", raising=False)
    for cwd in ("/private/var/folders/k3/T/kbeval-repo-x", "/tmp/repo", "/Users/x/kbeval-copy"):
        assert kb_capture.skip_reason({"cwd": cwd}, session(cwd=cwd)) == "temp-path"


def test_interactive_ok(monkeypatch):
    monkeypatch.delenv("KB_CAPTURE_FORK", raising=False)
    assert kb_capture.skip_reason({"cwd": "/Users/x/repo"}, session()) is None


def test_transcript_entries_skips_bad_lines(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "mode"}) + "\nnot json\n" + json.dumps({"type": "user"}) + "\n")
    assert [e["type"] for e in kb_capture.transcript_entries(t)] == ["mode", "user"]


def test_launch_cwd_is_first_recorded_cwd():
    entries = session(cwd="/Users/x/start") + [{**user("u2", "later"), "cwd": "/Users/x/elsewhere"}]
    assert kb_capture.launch_cwd(entries) == Path("/Users/x/start")


def test_inbox_none_without_index(tmp_path):
    assert kb_capture.inbox_for(tmp_path) is None
    (tmp_path / ".claude" / "knowledge").mkdir(parents=True)
    (tmp_path / ".claude" / "knowledge" / "index.json").write_text("{}")
    assert kb_capture.inbox_for(tmp_path) == tmp_path / ".claude" / "knowledge" / "inbox"


def test_worktree_resolves_main_checkout(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    git = lambda *a, cwd=main: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    git("worktree", "add", "-q", str(tmp_path / "wt"))
    (tmp_path / "wt" / "sub").mkdir()
    assert kb_capture.main_checkout(tmp_path / "wt" / "sub").resolve() == main.resolve()
    assert kb_capture.main_checkout(tmp_path / "nogit").resolve() == (tmp_path / "nogit").resolve()


def test_turn_count_since_marker():
    entries = session() + [user("u2", "two"), assistant("a2", "x"), user("u3", "three"), assistant("a3", "y")]
    assert kb_capture.user_turns_since(entries, None) == 3
    assert kb_capture.user_turns_since(entries, "u1") == 2
    assert kb_capture.last_user_uuid(entries) == "u3"


def test_turn_count_ignores_tool_results_and_meta():
    entries = session() + [
        {"type": "user", "uuid": "t1", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        user("m1", "<system-reminder>x</system-reminder>", isMeta=True),
        user("s1", "sub", isSidechain=True),
        user("u2", "real")]
    assert kb_capture.user_turns_since(entries, "u1") == 1
    assert kb_capture.last_user_uuid(entries) == "u2"


def test_session_model_uses_last_requested_model():
    entries = session() + [user("u2", "switch"), assistant("a2", "ok", model="claude-sonnet-5-5")]
    assert kb_capture.session_model(entries) == "claude-sonnet-5-5"
    assert kb_capture.session_model(session()) == "claude-opus-5-5[1m]"


def test_guard_allows_several_dirs(tmp_path):
    a, b = tmp_path / "inbox", tmp_path / "results"
    out = subprocess.run([sys.executable, str(GUARD), str(a), str(b)], input=json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(b / "r.json")}}), capture_output=True, text=True).stdout
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "allow"


NOW = time.time()  # sweep compares against real file mtimes


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_capture, "GATE_DIR", tmp_path / "gate")
    monkeypatch.setattr(kb_capture, "TEMP_MARKERS", ("kbeval",))  # pytest's tmp_path itself lives under /var/folders
    monkeypatch.delenv("KB_CAPTURE_FORK", raising=False)
    return tmp_path / "gate"


def make_inbox(tmp_path: Path, drafts: int = 0) -> Path:
    inbox = tmp_path / "repo" / ".claude" / "knowledge" / "inbox"
    inbox.mkdir(parents=True)
    (inbox.parent / "index.json").write_text("{}")
    (inbox / "_TEMPLATE.md").write_text("t")
    for i in range(drafts):
        (inbox / f"d{i}.md").write_text("d")
    return inbox


def long_session(turns: int) -> list[dict]:
    entries = session()
    for i in range(2, turns + 1):
        entries += [user(f"u{i}", f"msg {i}"), assistant(f"a{i}", "ok")]
    return entries


def test_state_roundtrip(gate):
    assert kb_capture.load_state("s1") == {}
    kb_capture.save_state("s1", {"marker": "u3"})
    assert kb_capture.load_state("s1") == {"marker": "u3"}


def owned_process(mode: str, sid: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "kb-capture-hook.py", mode, sid])


def test_fork_due_rules(gate, tmp_path):
    inbox = make_inbox(tmp_path)
    st = {"inbox": str(inbox), "last_reply_ts": NOW - 60, "marker": None, "fork": None}
    assert kb_capture.fork_due(st, long_session(5), "session-end", NOW, "s1") is None
    assert kb_capture.fork_due(st, long_session(4), "session-end", NOW, "s1") == "short"
    assert kb_capture.fork_due({**st, "last_reply_ts": NOW - 56 * 60}, long_session(5), "idle", NOW, "s1") == "cold"
    assert kb_capture.fork_due({**st, "last_reply_ts": NOW - 56 * 60}, long_session(5), "precompact", NOW, "s1") is None
    assert kb_capture.fork_due({**st, "inbox": None}, long_session(5), "session-end", NOW, "s1") == "no-kb"
    runner = owned_process("run", "s1")
    try:
        assert kb_capture.fork_due({**st, "fork": {"pid": runner.pid}}, long_session(5), "idle", NOW, "s1") == "running"
    finally:
        runner.kill()


def test_fork_due_inbox_full_sets_note(gate, tmp_path):
    st = {"inbox": str(make_inbox(tmp_path, drafts=30)), "last_reply_ts": NOW, "marker": None, "fork": None}
    assert kb_capture.fork_due(st, long_session(6), "session-end", NOW, "s1") == "inbox-full"
    assert "/kb:clean" in st["note"]


def test_lock_released_when_pid_dead(gate, tmp_path):
    dead = subprocess.Popen(["true"])
    dead.wait()
    st = {"inbox": str(make_inbox(tmp_path)), "last_reply_ts": NOW, "marker": None, "fork": {"pid": dead.pid}}
    assert kb_capture.fork_due(st, long_session(5), "session-end", NOW, "s1") is None


def test_fork_command_has_no_tool_flags(tmp_path):
    cmd = kb_capture.fork_command("sid-1", "claude-opus-5-5[1m]", [tmp_path / "inbox", tmp_path / "res"], "PROMPT", 1.0)
    assert cmd[1:9] == ["-p", "--resume", "sid-1", "--fork-session", "--no-session-persistence",
                        "--model", "claude-opus-5-5[1m]", "--permission-mode"]
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
    assert cmd[cmd.index("--max-budget-usd") + 1] == "1.0"
    assert cmd[-1] == "PROMPT"
    assert not {"--tools", "--disallowedTools", "--allowedTools", "--bare"} & set(cmd)
    hook = json.loads(cmd[cmd.index("--settings") + 1])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "kb-capture-guard.py" in hook and str(tmp_path / "inbox") in hook and str(tmp_path / "res") in hook


def fake_run(result_payload: dict | None, stdout: dict | str):
    def run(cmd, **kw):
        prompt = cmd[-1]
        result_path = Path(prompt.split("Write `")[1].split("`")[0]) if result_payload is not None else None
        if result_path:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result_payload))
        out = stdout if isinstance(stdout, str) else json.dumps(stdout)
        return subprocess.CompletedProcess(cmd, 0, out, "")
    return run


SPIKE = {"total_cost_usd": 0.12, "num_turns": 5, "subtype": "success", "result": "done",
         "modelUsage": {"m": {"cacheReadInputTokens": 690000, "cacheCreationInputTokens": 9900}}}


def started_state(gate, tmp_path, transcript: Path) -> None:
    inbox = make_inbox(tmp_path)
    kb_capture.save_state("s1", {"transcript": str(transcript), "cwd": str(tmp_path), "inbox": str(inbox),
                                 "model": "m", "marker": "u3", "segment_from": "msg 2",
                                 "last_reply_ts": NOW, "fork": {"pid": 1, "started": NOW, "trigger": "idle"}})


def test_run_fork_success_logs_and_notes(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    started_state(gate, tmp_path, t)
    inbox = Path(kb_capture.load_state("s1")["inbox"])
    (inbox / "2026-10-22-x.md").write_text("---\nintent: add\n---\n# Fee overflow is UB\n")
    run = fake_run({"drafts": [str(inbox / "2026-10-22-x.md")], "skipped": [{"claim": "c", "reason": "lookup"}]}, SPIKE)
    rec = kb_capture.run_fork("s1", "idle", "s1", runner=run)
    assert rec["drafts"] == 1 and rec["cost"] == 0.12 and rec["cache_read"] == 690000 and rec["error"] is None
    log = [json.loads(l) for l in (gate / "capture-log.jsonl").read_text().splitlines()]
    assert log[-1]["trigger"] == "idle"
    st = kb_capture.load_state("s1")
    assert st["fork"] is None and "Fee overflow is UB" in st["note"]


def test_run_fork_prompt_names_segment_start(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    started_state(gate, tmp_path, t)
    seen = {}

    def run(cmd, **kw):
        seen["prompt"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, json.dumps(SPIKE), "")
    kb_capture.run_fork("s1", "idle", "s1", runner=run)
    assert '"msg 2"' in seen["prompt"] and "{segment}" not in seen["prompt"]


def test_run_fork_failure_notes_error(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    started_state(gate, tmp_path, t)
    rec = kb_capture.run_fork("s1", "idle", "s1", runner=fake_run(None, "Error: something broke"))
    assert rec["error"] and kb_capture.load_state("s1")["fork"] is None
    assert "failed" in kb_capture.load_state("s1")["note"]


def test_copy_deleted_after_run(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    copy = tmp_path / "copy-1.jsonl"
    copy.write_text("")
    started_state(gate, tmp_path, t)
    kb_capture.run_fork("s1", "precompact", "copy-1", runner=fake_run({"drafts": [], "skipped": []}, SPIKE))
    assert not copy.exists() and t.exists()


def test_note_taken_once(gate):
    kb_capture.save_state("s1", {"note": "[kb-capture] x"})
    assert kb_capture.take_note("s1", NOW) == "[kb-capture] x"
    assert kb_capture.take_note("s1", NOW) is None


def test_note_soft_cap_warning(gate):
    gate.mkdir(parents=True)
    (gate / "capture-log.jsonl").write_text("".join(json.dumps({"ts": NOW - 10, "cost": 1.6}) + "\n" for _ in range(2)))
    kb_capture.save_state("s1", {"note": "[kb-capture] x"})
    note = kb_capture.take_note("s1", NOW)
    assert "$3.20" in note and "2 forks" in note and "soft cap $3" in note


def test_start_fork_locks_and_moves_marker(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("".join(json.dumps(e) + "\n" for e in long_session(6)))
    kb_capture.save_state("s1", {"transcript": str(t), "marker": "u2", "fork": None})
    spawned = []
    kb_capture.start_fork("s1", "session-end", "s1", spawn=lambda argv: spawned.append(argv) or 4242)
    st = kb_capture.load_state("s1")
    assert st["fork"]["pid"] == 4242 and st["marker"] == "u6" and st["segment_from"] == "msg 3"
    assert spawned[0][-3:] == ["s1", "session-end", "s1"]


def test_sweep_only_capture_files(gate, tmp_path):
    gate.mkdir(parents=True)
    old = NOW - 31 * 86400
    for name in ("capture-old.json", "router-log.jsonl", "abc.json"):
        (gate / name).write_text("x")
        os.utime(gate / name, (old, old))
    kb_capture.sweep(NOW)
    assert not (gate / "capture-old.json").exists()
    assert (gate / "router-log.jsonl").exists() and (gate / "abc.json").exists()


HOOK = SCRIPTS / "kb-capture-hook.py"
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("kb_capture_hook", HOOK)


def load_hook():
    mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(mod)
    return mod


def write_transcript(path: Path, entries: list[dict]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def test_stop_updates_state_and_spawns_idle(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", session(cwd=str(repo)))
    spawned = []
    monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: spawned.append(argv) or 777)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
    st = kb_capture.load_state("s1")
    assert st["model"] == "claude-opus-5-5[1m]" and st["last_reply_ts"] == NOW and st["idle_pid"] == 777
    assert st["inbox"] == str(repo / ".claude" / "knowledge" / "inbox")
    assert spawned[0][-3:] == ["idle", "s1", str(NOW)]


def test_stop_skips_headless(gate, tmp_path):
    hook = load_hook()
    t = write_transcript(tmp_path / "s1.jsonl", session(entrypoint="sdk-cli"))
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": "/Users/x/repo"}, now=NOW)
    assert kb_capture.load_state("s1") == {}


def test_session_end_starts_fork_when_due(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", [{**e, "cwd": str(repo)} if e.get("cwd") else e for e in long_session(6)])
    monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: 1)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
    started = []
    monkeypatch.setattr(hook.kb_capture, "start_fork", lambda sid, trig, rid, **k: started.append((sid, trig, rid)))
    hook.handle("session-end", {"session_id": "s1", "transcript_path": str(t), "reason": "clear"}, now=NOW + 5)
    assert started == [("s1", "session-end", "s1")]


def test_precompact_forks_from_copy(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", [{**e, "cwd": str(repo)} if e.get("cwd") else e for e in long_session(6)])
    monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: 1)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
    started = []
    monkeypatch.setattr(hook.kb_capture, "start_fork", lambda sid, trig, rid, **k: started.append(rid))
    hook.handle("precompact", {"session_id": "s1", "transcript_path": str(t)}, now=NOW + 5)
    copy = tmp_path / f"{started[0]}.jsonl"
    assert started[0] != "s1" and copy.read_text() == t.read_text()


def test_idle_skips_when_newer_reply(gate, tmp_path, monkeypatch):
    hook = load_hook()
    kb_capture.save_state("s1", {"last_reply_ts": NOW + 100})
    started = []
    monkeypatch.setattr(hook.kb_capture, "start_fork", lambda *a, **k: started.append(a))
    hook.idle("s1", NOW, sleep=lambda s: None, now=lambda: NOW + 45 * 60)
    assert started == []


def test_entry_noop_under_fork_env(gate, tmp_path, monkeypatch):
    monkeypatch.setenv("KB_CAPTURE_FORK", "1")
    out = subprocess.run([sys.executable, str(HOOK), "stop"], input="{}", capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == ""


def test_prompt_mode_emits_note_once(gate, capsys):
    hook = load_hook()
    kb_capture.save_state("s1", {"note": "[kb-capture] captured 1 draft"})
    hook.handle("prompt", {"session_id": "s1"}, now=NOW)
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["additionalContext"].startswith("[kb-capture] captured 1 draft")
    hook.handle("prompt", {"session_id": "s1"}, now=NOW)
    assert capsys.readouterr().out == ""


def test_entry_never_raises(gate, tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    env.pop("KB_CAPTURE_FORK", None)
    out = subprocess.run([sys.executable, str(HOOK), "stop"], input="not json", capture_output=True, text=True, env=env)
    assert out.returncode == 0
    assert "error" in (tmp_path / ".claude" / "kb-gate" / "capture-log.jsonl").read_text()



def test_lock_ignores_foreign_pid(gate, tmp_path):
    st = {"inbox": str(make_inbox(tmp_path)), "last_reply_ts": NOW, "marker": None, "fork": {"pid": os.getpid()}}
    assert kb_capture.fork_due(st, long_session(5), "session-end", NOW, "s1") is None


def test_stop_does_not_kill_foreign_pid(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", session(cwd=str(repo)))
    foreign = subprocess.Popen(["sleep", "30"])
    try:
        kb_capture.save_state("s1", {"idle_pid": foreign.pid})
        monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: 1)
        hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
        time.sleep(0.2)
        assert foreign.poll() is None
    finally:
        foreign.kill()


def test_stop_kills_own_idle_process(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", session(cwd=str(repo)))
    idle = owned_process("idle", "s1")
    kb_capture.save_state("s1", {"idle_pid": idle.pid})
    monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: 1)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
    assert idle.wait(timeout=5) is not None


def test_run_fork_budget_stop_is_failure(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    started_state(gate, tmp_path, t)
    stopped = {**SPIKE, "subtype": "error_max_budget_usd", "is_error": False}
    rec = kb_capture.run_fork("s1", "idle", "s1", runner=fake_run(None, stopped))
    assert rec["error"] == "error_max_budget_usd"
    assert "failed" in kb_capture.load_state("s1")["note"]


def test_run_fork_non_object_stdout_releases_lock(gate, tmp_path):
    t = tmp_path / "s1.jsonl"
    t.write_text("")
    started_state(gate, tmp_path, t)
    rec = kb_capture.run_fork("s1", "idle", "s1", runner=fake_run(None, "[1, 2]"))
    assert rec["error"] and kb_capture.load_state("s1")["fork"] is None


def test_guard_denies_on_bad_input(tmp_path):
    out = subprocess.run([sys.executable, str(GUARD), str(tmp_path)], input="not json", capture_output=True, text=True)
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_fork_command_quotes_guard_paths(tmp_path):
    import shlex
    odd = tmp_path / "it's a dir"
    cmd = kb_capture.fork_command("sid", "m", [odd], "P", 1.0)
    hook = json.loads(cmd[cmd.index("--settings") + 1])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert shlex.split(hook)[-1] == str(odd)


def test_precompact_copy_removed_when_start_fails(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", [{**e, "cwd": str(repo)} if e.get("cwd") else e for e in long_session(6)])
    monkeypatch.setattr(hook.kb_capture, "_spawn", lambda argv: 1)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)

    def boom(*a, **k):
        raise OSError("spawn failed")
    monkeypatch.setattr(hook.kb_capture, "start_fork", boom)
    with pytest.raises(OSError):
        hook.handle("precompact", {"session_id": "s1", "transcript_path": str(t)}, now=NOW + 5)
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == ["s1.jsonl"]


def test_stop_keeps_note_written_concurrently(gate, tmp_path, monkeypatch):
    hook = load_hook()
    repo = tmp_path / "repo"
    make_inbox(tmp_path)
    t = write_transcript(tmp_path / "s1.jsonl", session(cwd=str(repo)))
    kb_capture.save_state("s1", {"fork": {"pid": 1}})

    def runner_finishes_meanwhile(argv):
        st = kb_capture.load_state("s1")
        st.update(fork=None, note="[kb-capture] done")
        kb_capture.save_state("s1", st)
        return 5
    monkeypatch.setattr(hook.kb_capture, "_spawn", runner_finishes_meanwhile)
    hook.handle("stop", {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, now=NOW)
    st = kb_capture.load_state("s1")
    assert st["note"] == "[kb-capture] done" and st["fork"] is None and st["idle_pid"] == 5


def test_capture_model_override(gate, tmp_path):
    inbox = make_inbox(tmp_path)
    (inbox.parent / ".kb").mkdir()
    (inbox.parent / ".kb" / "config.json").write_text(json.dumps({"capture": {"model": "claude-haiku-5-5"}}))
    assert kb_capture.fork_model(inbox, long_session(2)) == "claude-haiku-5-5"
    (inbox.parent / ".kb" / "config.json").write_text(json.dumps({"capture": {"model": "session"}}))
    assert kb_capture.fork_model(inbox, long_session(2)) == "claude-opus-5-5[1m]"
