"""install.py (plugin mode): strip legacy settings hooks that would double-run, set env, report what is missing."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"))
import install  # noqa: E402

LEGACY = {"hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude/skills/knowledge-base/scripts/kb-prompt-gate.py stop"},
                        {"type": "command", "command": "echo other"}]}],
    "SessionStart": [{"hooks": [{"type": "command", "command": "bash ~/.claude/hooks/inject-kb-index.sh"}]}]}}


def commands(settings: dict) -> list[str]:
    return [h["command"] for groups in settings.get("hooks", {}).values() for g in groups for h in g["hooks"]]


def test_install_removes_legacy_hooks_only(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(LEGACY))
    install.install(f)
    s = json.loads(f.read_text())
    assert commands(s) == ["echo other"] and "SessionStart" not in s["hooks"]
    assert list(tmp_path.glob("settings.json.bak-*"))


def test_install_sets_env_and_is_idempotent(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("{}")
    install.install(f)
    assert install.install(f) == []
    assert json.loads(f.read_text())["env"]["CLAUDE_CODE_FORK_SUBAGENT"] == "1"


def test_check_reports_disabled_plugin_and_legacy_hooks(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(LEGACY))
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    monkeypatch.setattr(install, "CLAUDE_FALLBACK", tmp_path / "no-claude")
    monkeypatch.setattr(install, "PLUGIN_LINK", tmp_path / "skills" / "kb")
    report, ok = install.check(f)
    assert not ok
    assert "plugin kb is not installed" in report and "legacy hook" in report and "uv" in report


def test_check_finds_tools_in_known_locations(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    f.write_text("{}")
    tool = tmp_path / "graphify"
    tool.write_text("")
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    monkeypatch.setitem(install.KNOWN_LOCATIONS, "graphify", [tool])
    report, _ = install.check(f)
    assert "graphify" not in report
