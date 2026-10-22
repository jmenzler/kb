"""kb_redact: nothing secret or personal leaves the machine in a Jev request."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins" / "kb" / "scripts"))
import kb_redact  # noqa: E402
import kb_router  # noqa: E402

SECRETS = [
    "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdefghijkl",
    "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
    "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOP",
    "xoxb-123456789012-123456789012-AbCdEfGhIjKlMnOpQrStUvWx",
    "AKIAIOSFODNN7EXAMPLE",
    "AIzaSyA-1234567890abcdefghijklmnopqrstu",
    "sk_live_51AbCdEfGhIjKlMnOpQrStUvWx",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----",
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_known_secret_formats_are_masked(secret):
    out, n = kb_redact.redact(f"here: {secret} done")
    assert secret not in out and n >= 1 and "here:" in out and "done" in out


@pytest.mark.parametrize("text,leak", [
    ("db is postgres://trader:hunter2pass@db.internal:5432/x", "hunter2pass"),
    ("password = correct-horse-battery", "correct-horse-battery"),
    ('api_key: "q8w7e6r5t4y3"', "q8w7e6r5t4y3"),
    ("export TOKEN=abc123def456ghi", "abc123def456ghi"),
    ("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
    ("mail me at jane.doe@example.com", "jane.doe@example.com"),
])
def test_credentials_in_context_are_masked(text, leak):
    out, n = kb_redact.redact(text)
    assert leak not in out and n >= 1


def test_env_secret_values_are_masked_exactly(monkeypatch):
    monkeypatch.setenv("MY_SERVICE_TOKEN", "plainlookingvalue42")
    out, n = kb_redact.redact("the value plainlookingvalue42 appeared")
    assert "plainlookingvalue42" not in out and n == 1


def test_ordinary_text_is_untouched():
    text = "How does the median rule pick a value? See crates/sim/src/consensus.rs:120 and run cargo test."
    assert kb_redact.redact(text) == (text, 0)


def test_jev_request_body_never_contains_a_secret(monkeypatch, tmp_path):
    secret = SECRETS[0]
    sent = {}

    class Resp:
        def read(self):
            return json.dumps({"answers": {"q": {"noul": 0.5}}}).encode()

    def fake_urlopen(req, timeout):
        sent["body"] = req.data.decode()
        return Resp()
    monkeypatch.setattr(kb_router.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(kb_router.kb_config, "jev_key", lambda: "k")
    cfg = {"model": "m", "questions": {}, "combiner": {"intercept": 0, "coef": [1], "names": ["q"], "cut": 0.5}}
    kb_router.jev_p("my note", f"previous reply quoted {secret}", f"kb summary {secret}", cfg)
    assert secret not in sent["body"] and "my note" in sent["body"]
