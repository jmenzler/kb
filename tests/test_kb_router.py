"""kb_router.decide: local-confident, uncertain → Jev, Jev failure, no local model, disabled."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"))
import kb_router  # noqa: E402


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / ".claude" / "knowledge"
    (root / "rules").mkdir(parents=True)
    (root / "index.json").write_text(json.dumps({"description": "Test KB", "entries": {
        "rules": {"folder": "rules/", "description": "Wording rules. More text.", "topics": ["wording"]}}}))
    (root / "rules" / "index.json").write_text(json.dumps({"files": {"cv.md": {}, "letters.md": {}}}))
    monkeypatch.setattr(kb_router, "previous_turn", lambda _t, _c: "")
    monkeypatch.delenv("KB_ROUTER", raising=False)
    return root


def _local(p):
    return lambda _text, timeout=None: p


def test_confident_local_decides_without_jev(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(0.95))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: pytest.fail("Jev must not be called"))
    d = kb_router.decide("status of my application?", None, kb)
    assert d["route"] is True and d["source"] == "local"


def test_confident_local_skip(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(0.02))
    d = kb_router.decide("ok commit that", None, kb)
    assert d["route"] is False and d["source"] == "local"


def test_uncertain_local_asks_jev(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(0.5))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: 0.9)
    d = kb_router.decide("say starting 2027 not february", None, kb)
    assert d["route"] is True and d["source"] == "jev"


def test_jev_failure_keeps_local_decision(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(0.52))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: None)
    d = kb_router.decide("borderline", None, kb)
    assert d["source"] == "local-fallback"


def test_no_local_model_uses_jev(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(None))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: 0.1)
    d = kb_router.decide("what does = default do", None, kb)
    assert d["route"] is False and d["source"] == "jev"


def test_no_router_returns_none(kb, monkeypatch):
    monkeypatch.setattr(kb_router, "local_p", _local(None))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: None)
    assert kb_router.decide("anything", None, kb) is None


def test_disabled_and_missing_kb(kb, monkeypatch, tmp_path):
    monkeypatch.setenv("KB_ROUTER", "off")
    assert kb_router.decide("anything", None, kb) is None
    monkeypatch.delenv("KB_ROUTER")
    assert kb_router.decide("anything", None, tmp_path / "nowhere") is None


def test_local_mode_never_calls_jev(kb, monkeypatch):
    monkeypatch.setenv("KB_ROUTER", "local")
    monkeypatch.setattr(kb_router, "local_p", _local(0.5))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: pytest.fail("Jev must not be called"))
    assert kb_router.decide("borderline", None, kb)["source"] == "local-fallback"


def test_kb_summary_lists_folder_docs(kb):
    s = kb_router.kb_summary(kb, docs_per_folder=10)
    assert "Test KB" in s and "rules: Wording rules" in s and "[docs: cv, letters]" in s


def test_previous_turn_reads_last_assistant_text(tmp_path, monkeypatch):
    monkeypatch.undo()
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
        {"type": "user", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Should I commit?"}]}}]))
    assert kb_router.previous_turn(str(t), 100) == "Should I commit?"


def test_jev_mode_skips_local_model(kb, monkeypatch):
    monkeypatch.setenv("KB_ROUTER", "jev")
    monkeypatch.setattr(kb_router, "local_p", lambda *a, **k: pytest.fail("local model must not be called"))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: 0.9)
    d = kb_router.decide("anything", None, kb)
    assert d["route"] is True and d["source"] == "jev"


def test_jev_mode_falls_back_to_local_when_jev_fails(kb, monkeypatch):
    monkeypatch.setenv("KB_ROUTER", "jev")
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: None)
    monkeypatch.setattr(kb_router, "local_p", _local(0.95))
    assert kb_router.decide("anything", None, kb)["source"] == "local-fallback"


def test_cascade_is_the_default_and_on_is_an_alias(kb, monkeypatch):
    for mode in (None, "on", "cascade"):
        if mode:
            monkeypatch.setenv("KB_ROUTER", mode)
        monkeypatch.setattr(kb_router, "local_p", _local(0.5))
        monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: 0.9)
        assert kb_router.decide("x", None, kb)["source"] == "jev"
        monkeypatch.setattr(kb_router, "local_p", _local(0.99))
        assert kb_router.decide("x", None, kb)["source"] == "local"


def test_band_comes_from_config(kb, monkeypatch):
    (kb / ".kb").mkdir(exist_ok=True)
    (kb / ".kb" / "config.json").write_text(json.dumps({"router": {"band": 0.0}}))
    monkeypatch.setattr(kb_router, "local_p", _local(0.5))
    monkeypatch.setattr(kb_router, "jev_p", lambda *a, **k: pytest.fail("band 0 means the local model always decides"))
    assert kb_router.decide("x", None, kb)["source"] == "local"
