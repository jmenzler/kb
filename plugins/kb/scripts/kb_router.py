"""Should this chat message go through the KB first? Local model, Jev for the uncertain band, then fallbacks.

  local   Qwen3-Embedding-0.6B + logistic regression, served warm by kb-router-daemon.py over a socket
  jev     TypeSafe Jev (pinned model, six Noul questions + logistic combiner) for messages whose local
          score lies within `band` (logit distance) of the cutoff — about 30% of messages
  order   local confident → local decision · local uncertain → Jev, or the local decision if Jev fails ·
          no local model → Jev · neither → None (the caller falls back to keyword matching)

Configs: kb-router-local.json and kb-router.json (fitted offline). Mode, band and timeouts come from kb_config
(`features.router`: cascade|local|jev|off, `router` block); the TypeSafe key from kb_config.jev_key().
"""
from __future__ import annotations

import json
import math
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import kb_config
import kb_redact

HERE = Path(__file__).resolve().parent
GATE_DIR = Path.home() / ".claude" / "kb-gate"
SOCK = GATE_DIR / "router.sock"
LOG = GATE_DIR / "router-log.jsonl"
SPAWN_MARK = GATE_DIR / "router-spawn"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
LOCAL_TIMEOUT = 0.3
JEV_TIMEOUT = 1.0
SPAWN_EVERY = 120  # seconds between daemon start attempts


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def local_p(text: str, timeout: float = LOCAL_TIMEOUT) -> float | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(SOCK))
            s.sendall((json.dumps({"text": text}) + "\n").encode())
            reply = json.loads(s.makefile().readline())
        return float(reply["p"]) if "p" in reply else None
    except (OSError, ValueError, KeyError):
        return None


def ensure_daemon() -> None:
    """Start the local model server in the background unless it answers or was started recently."""
    if local_p("ping", timeout=0.2) is not None:
        return
    if SPAWN_MARK.exists() and time.time() - SPAWN_MARK.stat().st_mtime < SPAWN_EVERY:
        return
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    SPAWN_MARK.touch()
    with open(GATE_DIR / "router-daemon.log", "ab") as out:
        subprocess.Popen([uv, "run", "--no-project", "--with", "sentence-transformers", "--with", "numpy",
                          "python", str(HERE / "kb-router-daemon.py")],
                         stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)


def kb_summary(kb_root: Path, docs_per_folder: int) -> str:
    """Root description + each entry's first sentence, topics and (for folders) doc names."""
    j = json.loads((kb_root / "index.json").read_text())
    entries = j.get("entries") or {e["path"]: e for e in j.get("folders", [])}
    lines = [j.get("description") or j.get("purpose") or kb_root.parent.parent.name]
    for name, e in entries.items():
        line = f"- {name.rstrip('/')}: {e.get('description', '').split('. ')[0][:150]}"
        line += f" [topics: {', '.join(e.get('topics', []))}]"
        folder = e.get("folder") or e.get("path", "")
        index = kb_root / folder / "index.json"
        if folder.endswith("/") and index.exists():
            docs = [d.removesuffix(".md") for d in json.loads(index.read_text()).get("files", {})]
            more = f", +{len(docs) - docs_per_folder} more" if len(docs) > docs_per_folder else ""
            line += f" [docs: {', '.join(docs[:docs_per_folder])}{more}]"
        lines.append(line)
    return "\n".join(lines)


def previous_turn(transcript: str | None, chars: int) -> str:
    """Text of the last assistant turn in the transcript (tail only, so long sessions stay cheap)."""
    if not transcript or not Path(transcript).exists():
        return ""
    with open(transcript, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 400_000))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        parts = e.get("message", {}).get("content") or []
        text = " ".join(b.get("text", "") for b in parts if isinstance(b, dict) and b.get("type") == "text").strip()
        if text:
            return text[-chars:]
    return ""


def jev_p(message: str, prev: str, kb_text: str, cfg: dict, timeout: float = JEV_TIMEOUT) -> float | None:
    key = kb_config.jev_key()
    if not key:
        return None
    message, prev, kb_text = (kb_redact.redact(t)[0] for t in (message, prev, kb_text))
    body = json.dumps({"model": cfg["model"], "questions": cfg["questions"],
                       "state": {"kb": kb_text, "previous_turn": prev or "(none)", "user_message": message}}).encode()
    req = urllib.request.Request(JEV_URL, body, {"Content-Type": "application/json",
                                                 "Authorization": f"Bearer {key}"})
    try:
        answers = json.loads(urllib.request.urlopen(req, timeout=timeout).read())["answers"]
        c = cfg["combiner"]
        z = c["intercept"] + sum(w * answers[q]["noul"] for w, q in zip(c["coef"], c["names"]))
        return 1 / (1 + math.exp(-z))
    except (OSError, ValueError, KeyError):
        return None


def decide(message: str, transcript: str | None, kb_root: Path) -> dict | None:
    """Route decision with provenance, or None when no router answers (the caller falls back to keywords).

    Modes (kb_config `features.router`): cascade = local model, Jev for its uncertain band · local = local model
    only · jev = Jev for every message, local model if Jev fails · off = None."""
    mode = kb_config.feature("router", kb_root) if (kb_root / "index.json").exists() else "off"
    if mode == "off":
        return None
    t0 = time.perf_counter()
    cfg = kb_config.load(kb_root)["router"]
    local_cfg = json.loads((HERE / "kb-router-local.json").read_text())
    jev_cfg = json.loads((HERE / "kb-router.json").read_text())
    band = local_cfg["band"] if cfg["band"] is None else cfg["band"]

    def ask_jev() -> float | None:
        prev = previous_turn(transcript, jev_cfg["prev_chars"])
        return jev_p(message, prev, kb_summary(kb_root, jev_cfg["docs_per_folder"]), jev_cfg, cfg["jev_timeout_s"])

    # A message carrying a secret never leaves the machine: the local model decides it.
    secret_in_message = kb_redact.redact(message)[1] > 0
    if secret_in_message and mode in ("cascade", "jev"):
        mode = "local"
    out: dict = {"mode": mode, "redacted": secret_in_message}
    p_local = None if mode == "jev" else local_p(message, cfg["local_timeout_s"])
    uncertain = p_local is None or abs(_logit(p_local) - _logit(local_cfg["cut"])) <= band
    if mode != "jev" and not uncertain:
        out.update(p_local=p_local, route=p_local >= local_cfg["cut"], source="local")
    else:
        p_jev = ask_jev() if mode in ("cascade", "jev") else None
        if p_jev is None and mode == "jev":
            p_local = local_p(message, cfg["local_timeout_s"])
        out.update(p_local=p_local, p_jev=p_jev)
        if p_jev is not None:
            out.update(route=p_jev >= jev_cfg["combiner"]["cut"], source="jev")
        elif p_local is not None:
            out.update(route=p_local >= local_cfg["cut"], source="local-fallback")
        else:
            return None
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    return out


def log(record: dict) -> None:
    if isinstance(record.get("text"), str):
        record = {**record, "text": kb_redact.redact(record["text"])[0]}
    try:
        GATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
