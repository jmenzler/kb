"""kb_config: one KB-root resolver and a layered feature switchboard (defaults < global < repo < env)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"))
import kb_config  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    for var in ("KB_HOOKS", "KB_ROUTER", "KB_ROOT", "KB_CAPTURE_FORK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(kb_config, "GLOBAL_CONFIG", tmp_path / "global.json")
    return tmp_path


def make_kb(repo: Path, cfg: dict | None = None) -> Path:
    kb = repo / ".claude" / "knowledge"
    (kb / ".kb").mkdir(parents=True)
    (kb / "index.json").write_text("{}")
    if cfg is not None:
        (kb / ".kb" / "config.json").write_text(json.dumps(cfg))
    return kb


def test_defaults_without_any_config(env):
    kb = make_kb(env / "repo")
    assert kb_config.feature("capture", kb) is True
    assert kb_config.feature("prompt_gate", kb) == "gate"
    assert kb_config.feature("router", kb) == "on"
    assert kb_config.load(kb)["capture"]["min_turns"] == 5


def test_repo_overrides_global(env):
    kb_config.GLOBAL_CONFIG.write_text(json.dumps({"features": {"capture": False, "router": "local"}}))
    kb = make_kb(env / "repo", {"features": {"capture": True}})
    assert kb_config.feature("capture", kb) is True
    assert kb_config.feature("router", kb) == "local"


def test_env_overrides_repo(env, monkeypatch):
    kb = make_kb(env / "repo", {"features": {"router": "on"}})
    monkeypatch.setenv("KB_ROUTER", "off")
    assert kb_config.feature("router", kb) == "off"


def test_kill_switch_turns_everything_off(env, monkeypatch):
    kb = make_kb(env / "repo")
    monkeypatch.setenv("KB_HOOKS", "off")
    assert not any(kb_config.enabled(name, kb) for name in kb_config.DEFAULTS["features"])


def test_fork_env_turns_everything_off(env, monkeypatch):
    kb = make_kb(env / "repo")
    monkeypatch.setenv("KB_CAPTURE_FORK", "1")
    assert not kb_config.enabled("index_inject", kb) and not kb_config.enabled("related_docs", kb)


def test_legacy_clean_enabled_maps_to_clean_nudge(env):
    kb = make_kb(env / "repo", {"clean": {"enabled": False}})
    assert kb_config.feature("clean_nudge", kb) is False


def test_no_kb_means_nothing_enabled(env):
    assert kb_config.enabled("capture", env / "nowhere" / ".claude" / "knowledge") is False


def test_bad_json_falls_back_to_defaults(env):
    kb = make_kb(env / "repo")
    (kb / ".kb" / "config.json").write_text("{not json")
    assert kb_config.feature("capture", kb) is True


def test_kb_root_env_wins(env, monkeypatch):
    monkeypatch.setenv("KB_ROOT", str(env / "x"))
    assert kb_config.kb_root(env) == env / "x"


def test_kb_root_resolves_worktree_to_main_checkout(env):
    main = env / "main"
    main.mkdir()
    git = lambda *a: subprocess.run(["git", *a], cwd=main, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i")
    git("worktree", "add", "-q", str(env / "wt"))
    make_kb(main)
    (env / "wt" / "sub").mkdir()
    assert kb_config.kb_root(env / "wt" / "sub").resolve() == (main / ".claude" / "knowledge").resolve()


def test_kb_root_falls_back_to_cwd(env):
    assert kb_config.kb_root(env / "plain") == env / "plain" / ".claude" / "knowledge"


def test_cli_root_prints_kb_only_when_feature_enabled(env):
    make_kb(env / "repo", {"features": {"index_inject": False}})
    run = lambda feat: subprocess.run([sys.executable, str(Path(kb_config.__file__)), "root", "--feature", feat],
                                      cwd=env / "repo", capture_output=True, text=True,
                                      env={"HOME": str(env), "PATH": "/usr/bin:/bin"})
    assert run("index_inject").returncode == 1
    out = run("related_docs")
    assert out.returncode == 0 and out.stdout.strip().endswith(".claude/knowledge")


def test_show_reports_sources(env, monkeypatch):
    kb_config.GLOBAL_CONFIG.write_text(json.dumps({"features": {"router": "local"}}))
    kb = make_kb(env / "repo", {"features": {"capture": False}})
    monkeypatch.setenv("KB_HOOKS", "")
    shown = kb_config.show(kb)
    assert "router = local  (global)" in shown and "capture = False  (repo)" in shown and "related_docs = True  (default)" in shown
