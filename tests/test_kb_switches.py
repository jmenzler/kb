"""Every automatic hook honours its kb_config switch, and nothing runs where there is no KB."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"
INJECT = SCRIPTS / "inject-kb-index.sh"
sys.path.insert(0, str(SCRIPTS))
import kb_config  # noqa: E402


def make_kb(repo: Path, features: dict | None = None) -> Path:
    kb = repo / ".claude" / "knowledge"
    for folder in ("a", "b"):
        (kb / folder).mkdir(parents=True)
        (kb / folder / "index.json").write_text(json.dumps({"files": {f"{folder}doc.md": {"topics": ["shared"]}}}))
        (kb / folder / f"{folder}doc.md").write_text(f"# {folder}\n")
    (kb / "index.json").write_text(json.dumps({"description": "Test KB", "entries": {
        "a": {"folder": "a/", "description": "A docs", "topics": ["cat_a"]},
        "b": {"folder": "b/", "description": "B docs", "topics": ["cat_b"]}}}))
    (kb / "topics.json").write_text(json.dumps(["shared", "cat_a", "cat_b"]))
    (kb / ".kb").mkdir()
    if features is not None:
        (kb / ".kb" / "config.json").write_text(json.dumps({"features": features}))
    return kb


def run(script: str, args: list[str], payload: dict | str, cwd: Path, home: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KB_", "CLAUDE"))}
    env["HOME"] = str(home)
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], input=data, cwd=cwd,
                          capture_output=True, text=True, env=env)


def test_show_related_honours_related_docs(tmp_path):
    on, off = make_kb(tmp_path / "on"), make_kb(tmp_path / "off", {"related_docs": False})
    for kb, expect in ((on, True), (off, False)):
        out = run("show-related.py", [], {"tool_input": {"file_path": str(kb / "a" / "adoc.md")}}, kb.parent.parent, tmp_path)
        assert ("bdoc" in out.stdout) is expect, out.stdout + out.stderr


def test_validate_topics_honours_topic_validation(tmp_path):
    on, off = make_kb(tmp_path / "on"), make_kb(tmp_path / "off", {"topic_validation": False})
    for kb, expect in ((on, True), (off, False)):
        bad = json.dumps({"files": {"adoc.md": {"topics": ["zzz_unknown"]}}})
        out = run("validate-topics.py", [], {"tool_input": {"file_path": str(kb / "a" / "index.json"), "content": bad}},
                  tmp_path, tmp_path)
        assert ("deny" in out.stdout) is expect, out.stdout + out.stderr


def test_clean_stop_honours_clean_nudge(tmp_path):
    for name, feats, expect in (("on", None, True), ("off", {"clean_nudge": False}, False)):
        kb = make_kb(tmp_path / name, feats)
        (kb / ".kb" / "pending-clean-ask.json").write_text(json.dumps({"message": "run clean?"}))
        out = run("kb-clean-stop.py", [], {"session_id": "s", "cwd": str(kb.parent.parent)}, kb.parent.parent, tmp_path)
        assert ("block" in out.stdout) is expect, out.stdout + out.stderr


def test_inject_index_honours_index_inject(tmp_path):
    on, off = make_kb(tmp_path / "on"), make_kb(tmp_path / "off", {"index_inject": False})
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("KB_")}, "HOME": str(Path.home())}
    out_on = subprocess.run(["bash", str(INJECT)], cwd=on.parent.parent, capture_output=True, text=True, env=env).stdout
    out_off = subprocess.run(["bash", str(INJECT)], cwd=off.parent.parent, capture_output=True, text=True, env=env).stdout
    assert "<kb-available>" in out_on and out_off == ""


def _gate_module(monkeypatch, kb: Path):
    monkeypatch.setenv("KB_ROOT", str(kb))
    for name in ("kb_graph", "kb_router"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("kb_prompt_gate", SCRIPTS / "kb-prompt-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import kb_router
    calls = {"daemon": 0, "log": 0}
    monkeypatch.setattr(kb_router, "ensure_daemon", lambda: calls.__setitem__("daemon", calls["daemon"] + 1))
    monkeypatch.setattr(kb_router, "log", lambda r: calls.__setitem__("log", calls["log"] + 1))
    monkeypatch.setattr(kb_router, "local_p", lambda *a, **k: None)
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_gate_path", lambda sid: kb.parent / f"gate-{sid}.json")
    return mod, calls


def test_prompt_gate_no_kb_spawns_nothing(tmp_path, monkeypatch, capsys):
    mod, calls = _gate_module(monkeypatch, tmp_path / "nokb" / ".claude" / "knowledge")
    mod._prompt({"session_id": "s", "prompt": "how does the adoc design work?"})
    assert calls == {"daemon": 0, "log": 0} and capsys.readouterr().out == ""


def test_prompt_gate_router_off_spawns_no_daemon(tmp_path, monkeypatch):
    kb = make_kb(tmp_path / "r", {"router": "off"})
    mod, calls = _gate_module(monkeypatch, kb)
    mod._prompt({"session_id": "s", "prompt": "how does the adoc design work?"})
    assert calls["daemon"] == 0


def test_prompt_gate_hint_mode_never_gates(tmp_path, monkeypatch, capsys):
    kb = make_kb(tmp_path / "h", {"prompt_gate": "hint", "router": "off"})
    mod, _ = _gate_module(monkeypatch, kb)
    mod._prompt({"session_id": "s", "prompt": "how does the adoc shared design work? ??"})
    out = capsys.readouterr().out
    assert "KB MATCH" not in out and not (kb.parent / "gate-s.json").exists()


def test_prompt_gate_off_is_silent(tmp_path, monkeypatch, capsys):
    kb = make_kb(tmp_path / "o", {"prompt_gate": "off"})
    mod, calls = _gate_module(monkeypatch, kb)
    mod._prompt({"session_id": "s", "prompt": "how does the adoc design work? ??"})
    assert capsys.readouterr().out == "" and calls["log"] == 0


def _capture_stop(tmp_path: Path, repo: Path) -> Path:
    t = tmp_path / "s1.jsonl"
    t.write_text(json.dumps({"type": "user", "uuid": "u1", "cwd": str(repo), "entrypoint": "cli",
                             "message": {"content": "hi"}}) + "\n" + json.dumps(
        {"type": "assistant", "uuid": "a1", "requestedModel": "m", "message": {"content": []}}) + "\n")
    run("kb-capture-hook.py", ["stop"], {"session_id": "s1", "transcript_path": str(t), "cwd": str(repo)}, repo, tmp_path)
    return tmp_path / ".claude" / "kb-gate" / "capture-s1.json"


def test_capture_stop_skips_repo_without_kb(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    assert not _capture_stop(tmp_path, repo).exists()


def test_capture_stop_honours_capture_switch(tmp_path):
    kb = make_kb(tmp_path / "c", {"capture": False})
    assert not _capture_stop(tmp_path, kb.parent.parent).exists()


def test_capture_settings_come_from_config(tmp_path):
    kb = tmp_path / "k" / ".claude" / "knowledge"
    (kb / ".kb").mkdir(parents=True)
    (kb / "index.json").write_text("{}")
    (kb / ".kb" / "config.json").write_text(json.dumps({"capture": {"min_turns": 2}}))
    import kb_capture
    assert kb_capture.settings(kb / "inbox")["min_turns"] == 2


def test_pretool_accepts_plugin_skill_name(tmp_path, monkeypatch, capsys):
    kb = make_kb(tmp_path / "p")
    mod, _ = _gate_module(monkeypatch, kb)
    gate = kb.parent / "gate-s.json"
    gate.write_text(json.dumps({"docs": ["a/adoc.md"]}))
    mod._pretool({"session_id": "s", "tool_name": "Skill", "tool_input": {"skill": "kb:base"}})
    assert json.loads(gate.read_text())["skill"] is True and capsys.readouterr().out == ""


def test_session_start_links_stable_plugin_path(tmp_path):
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("KB_")}, "HOME": str(tmp_path)}
    subprocess.run(["bash", str(INJECT)], cwd=tmp_path, capture_output=True, text=True, env=env)
    link = tmp_path / ".claude" / "kb"
    assert link.is_symlink() and link.resolve() == SCRIPTS.parent.resolve()


def test_missing_dictionary_means_no_jargon(tmp_path, monkeypatch):
    mod, _ = _gate_module(monkeypatch, make_kb(tmp_path / "d"))
    monkeypatch.setattr(mod, "DICT", tmp_path / "no-words")
    monkeypatch.setattr(mod, "_english", None)
    assert mod._is_jargon("signal") is False and mod._is_jargon("asyncio") is False


def launch_transcript(tmp_path: Path, launch: Path) -> Path:
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "mode"}) + "\n" + json.dumps(
        {"type": "user", "cwd": str(launch), "message": {"content": "hi"}}) + "\n")
    return t


def test_session_kb_root_uses_launch_dir(tmp_path):
    kb = make_kb(tmp_path / "repo")
    t = launch_transcript(tmp_path, kb.parent.parent)
    assert kb_config.session_kb_root({"transcript_path": str(t), "cwd": str(tmp_path)}) == kb
    assert kb_config.session_kb_root({"cwd": str(kb.parent.parent)}) == kb


def test_gate_follows_launch_dir_after_cwd_drift(tmp_path):
    kb = make_kb(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    t = launch_transcript(tmp_path, kb.parent.parent)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KB_", "CLAUDE"))}
    env.update(HOME=str(tmp_path), KB_ROUTER="off")
    out = subprocess.run([sys.executable, str(SCRIPTS / "kb-prompt-gate.py"), "prompt"], cwd=elsewhere, env=env,
                         input=json.dumps({"session_id": "s", "transcript_path": str(t), "cwd": str(elsewhere),
                                           "prompt": "how does the adoc design work? ??"}),
                         capture_output=True, text=True)
    assert "KB MATCH" in out.stdout, out.stdout + out.stderr


def test_show_related_finds_kb_from_file_path(tmp_path):
    kb = make_kb(tmp_path / "repo")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = run("show-related.py", [], {"tool_input": {"file_path": str(kb / "a" / "adoc.md")}}, elsewhere, tmp_path)
    assert "bdoc" in out.stdout, out.stdout + out.stderr


def test_clean_stop_follows_launch_dir(tmp_path):
    kb = make_kb(tmp_path / "repo")
    (kb / ".kb" / "pending-clean-ask.json").write_text(json.dumps({"message": "run clean?"}))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    t = launch_transcript(tmp_path, kb.parent.parent)
    out = run("kb-clean-stop.py", [], {"session_id": "s", "cwd": str(elsewhere), "transcript_path": str(t)}, elsewhere, tmp_path)
    assert "block" in out.stdout, out.stdout + out.stderr


def make_wide_kb(repo: Path, n: int) -> Path:
    kb = repo / ".claude" / "knowledge"
    entries = {}
    for i in range(n):
        f = f"f{i}"
        (kb / f).mkdir(parents=True)
        desc = f"Doc {i} explains the shared mechanism. " + "x" * 300
        topics = ["shared"] if i < 6 else [f"solo{i}"]  # 6 of 30 docs: not a hub topic
        (kb / f / "index.json").write_text(json.dumps({"files": {f"doc{i}.md": {"description": desc, "topics": topics}}}))
        (kb / f / f"doc{i}.md").write_text(f"# {i}\n")
        entries[f] = {"folder": f"{f}/", "description": f"folder {i}", "topics": [f"cat{i}"]}
    (kb / "index.json").write_text(json.dumps({"description": "Wide KB", "entries": entries}))
    return kb


def related(kb: Path, doc: str, sid: str, home: Path) -> str:
    return run("show-related.py", [], {"session_id": sid, "tool_input": {"file_path": str(kb / doc)}},
               kb.parent.parent, home).stdout


def test_related_caps_and_shortens(tmp_path):
    kb = make_wide_kb(tmp_path / "w", 30)
    out = json.loads(related(kb, "f0/doc0.md", "s1", tmp_path))["hookSpecificOutput"]["additionalContext"]
    listed = [l for l in out.splitlines()[1:] if l.startswith("  doc")]
    assert len(listed) == 4
    assert all(len(l) < 160 for l in listed) and "xxxxxxxx" not in out


def test_related_does_not_repeat_within_session(tmp_path):
    kb = make_wide_kb(tmp_path / "w", 30)
    first = related(kb, "f0/doc0.md", "s1", tmp_path)
    second = related(kb, "f1/doc1.md", "s1", tmp_path)
    shown_first = {l.split()[0] for l in json.loads(first)["hookSpecificOutput"]["additionalContext"].splitlines()[1:]}
    shown_second = {l.split()[0] for l in json.loads(second)["hookSpecificOutput"]["additionalContext"].splitlines()[1:]} if second else set()
    assert not (shown_first & shown_second) and "doc0" not in shown_second
    assert related(kb, "f2/doc2.md", "s2", tmp_path)  # a new session starts fresh
