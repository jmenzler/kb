#!/usr/bin/env python3
"""Force a KB read before answering any message that touches the KB.

  prompt mode (UserPromptSubmit): kb_router decides whether the message needs the KB (local
      model, Jev for uncertain messages); keyword matching against doc topics, filenames and
      descriptions supplies the read list, and decides alone when no router is available.
      A routed message gets the read list as a mandatory pause and arms a per-session gate in
      `~/.claude/kb-gate/<session_id>.json`.
  stop mode (Stop): if the gate is armed and no KB doc was Read (or kb-query run) since
      the last user message, block the stop once and order the traversal.

FAIL-SILENT like the other KB hooks — an error never blocks a prompt or a stop.
Manual test: `kb-prompt-gate.py match "<message>"` prints the matched docs.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_DOCS = 8
MIN_SCORE = 2
MIN_WORDS = 2  # distinct message words; one shared word is coincidence
QUESTION = re.compile(
    r"^\s*(?:quick one[,:]?\s*)?(how|why|what|which|when|where|who|should|does|do|did|is|are|"
    r"was|were|explain)\b", re.IGNORECASE)
REQUEST = re.compile(r"^\s*(can|could|would|will)\s+(you|u)\b", re.IGNORECASE)
STRONG = 2  # topic / filename token hit
WEAK = 1  # description token hit
# A token in more than this share of docs is a category word, not a signal.
GENERIC_SHARE = 0.25
PREFIX = 5

STOPWORDS = set("""
about above after again against also because been before being below between both
could does doing done down during each from further have having here into itself just
more most much only other over same should some such than that their them then there
these they this those through under until very want what when where which while will
with would your yours quick good idea give make need like know tell think thing please
work didnt dont even knowledge base skill skills read file files invoke session hook
open code still pure doesnt right implement online project projects change prompt prompts user users
""".split())
# Short topic parts that are plain English, not abbreviations like oa, cv, hft.
SHORT_STOP = set("""
a an and are as at by do for go gap in is it leg my new no of old on one or per so the
to two up us use vs we why all any get run set
""".split())
RARE_DF = 2  # a topic/filename token owned by this few docs is specific on its own
DICT = Path("/usr/share/dict/words")
FORCE = "??"  # user override: gate this message even without a match
_english: set[str] | None = None


def _is_jargon(token: str) -> bool:
    """Not an English word: rare jargon (asyncio, tsdb, oa) is a signal alone, 'signal' isn't."""
    global _english
    if _english is None:
        _english = ({w.strip().lower() for w in DICT.read_text().splitlines()}
                    if DICT.exists() else set())
    if not _english:  # no word list on this machine: no jargon signal rather than everything jargon
        return False
    stems = {token, token.rstrip("s"), token.removesuffix("es"), token.removesuffix("ed"),
             token.removesuffix("ing"), token.removesuffix("er")}
    return not (stems & _english)


def _parts(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _strong_tokens(names: list[str]) -> set[str]:
    """Topic/filename tokens, plus short abbreviations and short parts glued to a neighbour."""
    out: set[str] = set()
    for name in names:
        parts = _parts(name)
        out |= _tokens(" ".join(parts))
        out |= {p for p in parts if 2 <= len(p) < 4 and p not in SHORT_STOP}
        out |= {a + b for a, b in itertools.pairwise(parts) if min(len(a), len(b)) < 4}
    return out


def _message_tokens(message: str, short_vocab: set[str]) -> set[str]:
    return _tokens(message) | {w for w in _parts(message) if w in short_vocab}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) >= 4 and w not in STOPWORDS}


def _hit(word: str, vocab: set[str]) -> bool:
    if word in vocab:
        return True
    if len(word) < PREFIX:
        return False
    # Inflections only: blocks ~ block, never blocks ~ blockchain.
    return any(abs(len(word) - len(v)) <= 3
               and _common_prefix(word, v) >= max(PREFIX, min(len(word), len(v)) - 2)
               for v in vocab)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def match_docs(message: str) -> list[tuple[int, str]]:
    import kb_graph

    topics = kb_graph._load_doc_topics()
    if not topics:
        return []
    descs = kb_graph.doc_descriptions()
    strong = {d: _strong_tokens([*ts, Path(d).stem]) for d, ts in topics.items()}
    weak = {d: _tokens(descs.get(d, "")) for d in topics}

    df: dict[str, int] = {}
    for d in topics:
        for t in strong[d] | weak[d]:
            df[t] = df.get(t, 0) + 1
    limit = max(2, int(len(topics) * GENERIC_SHARE))
    generic = {t for t, c in df.items() if c > limit}

    short_vocab = {t for d in topics for t in strong[d] if len(t) < 4}
    words = _message_tokens(message, short_vocab) - generic
    strong_df: dict[str, int] = {}
    for d in topics:
        for t in strong[d]:
            strong_df[t] = strong_df.get(t, 0) + 1
    scored = []
    for d in topics:
        if kb_graph.is_excluded(d):
            continue
        s = strong[d] - generic
        w = weak[d] - generic
        hits = [STRONG if _hit(x, s) else WEAK if _hit(x, w) else 0 for x in words]
        rare = any(strong_df.get(t, 0) <= RARE_DF and _is_jargon(t)
                   for x in words for t in s if _hit(x, {t}))
        if rare or (sum(hits) >= MIN_SCORE and sum(1 for h in hits if h) >= MIN_WORDS):
            scored.append((sum(hits), d))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[:MAX_DOCS]


def keyword_docs(message: str) -> list[str]:
    """Docs owning a topic or filename whose every word appears in the message."""
    import kb_graph

    topics = kb_graph._load_doc_topics(inherit=False)
    owners: dict[str, set[str]] = {}
    for d, ts in topics.items():
        if kb_graph.is_excluded(d):
            continue
        for k in [*ts, Path(d).stem]:
            owners.setdefault(k.lower(), set()).add(d)
    limit = max(2, int(len(topics) * GENERIC_SHARE))
    words = set(re.findall(r"[a-z0-9]+", message.lower()))
    found: dict[str, int] = {}
    for k, docs in owners.items():
        parts = re.findall(r"[a-z0-9]+", k)
        if len(docs) > limit or all(p in STOPWORDS or len(p) < 4 for p in parts):
            continue
        # Short parts (ai, oa, us) must match exactly; longer ones allow inflection.
        if all(p in words if len(p) < 4 else _hit(p, words) for p in parts):
            for d in docs:
                found[d] = found.get(d, 0) + 1
    return sorted(found, key=lambda d: (-found[d], d))


def is_knowledge_question(message: str) -> bool:
    if REQUEST.match(message):
        return False
    return "?" in message or bool(QUESTION.match(message))


def classify(message: str) -> tuple[str | None, list[str]]:
    """GATE on a whole-keyword hit or a scored knowledge question; HINT on a scored match."""
    keyed = keyword_docs(message)
    scored = [d for _, d in match_docs(message)]
    docs = list(dict.fromkeys(keyed + scored))[:MAX_DOCS]
    if FORCE in message or keyed or (scored and is_knowledge_question(message)):
        return "GATE", docs
    return ("HINT", docs) if docs else (None, [])


def _is_kb_skill(name: str) -> bool:
    return name in ("kb:base", "base") or name.endswith("knowledge-base")


def _gate_path(session_id: str) -> Path:
    # Keyed by session, not cwd: the shell cwd can move between prompt and stop.
    return Path.home() / ".claude" / "kb-gate" / f"{session_id}.json"


def _sweep(now: float) -> None:
    """Once a day: drop stale per-session gate files and roll the router log over at 5 MB."""
    gate_dir = Path.home() / ".claude" / "kb-gate"
    stamp = gate_dir / "gate-sweep.stamp"
    if not gate_dir.exists() or (stamp.exists() and now - stamp.stat().st_mtime < 86400):
        return
    for f in gate_dir.glob("*.json"):
        if not f.name.startswith("capture-") and now - f.stat().st_mtime > 2 * 86400:
            f.unlink(missing_ok=True)
    log = gate_dir / "router-log.jsonl"
    if log.exists() and log.stat().st_size > 5_000_000:
        log.replace(gate_dir / "router-log.1.jsonl")
    stamp.touch()


def _route(prompt: str, payload: dict, keyword_tier: str | None, kb_root: Path) -> str | None:
    """Router verdict as a tier (GATE / None), or the keyword tier when no router answers."""
    import kb_router
    import kb_config
    decision = kb_router.decide(prompt, payload.get("transcript_path"), kb_root)
    uses_local = kb_config.feature("router", kb_root) in ("cascade", "local")
    if uses_local and (decision is None or decision.get("p_local") is None):
        kb_router.ensure_daemon()
    kb_router.log({"ts": round(time.time()), "session": payload.get("session_id"), "keyword": keyword_tier,
                   **(decision or {"source": "keyword"}), "text": prompt[:200]})
    if decision is None:
        return keyword_tier
    return "GATE" if decision["route"] else None


def _prompt(payload: dict) -> None:
    import kb_config
    import kb_graph
    sid = payload.get("session_id")
    prompt = payload.get("prompt") or ""
    kb_root = Path(kb_graph._KB_ROOT)
    gate = _gate_path(sid) if sid else None
    if gate and gate.exists():
        gate.unlink()
    if not kb_config.enabled("prompt_gate", kb_root):
        return
    _sweep(time.time())
    # Task notifications and system reminders arrive as prompts but carry no user intent.
    machine = prompt.lstrip().startswith(("<task-notification", "<system-reminder"))
    tier, docs = (None, []) if machine else classify(prompt)
    if not machine and FORCE not in prompt and kb_config.enabled("router", kb_root):
        try:
            routed = _route(prompt, payload, tier, kb_root)
        except Exception:  # noqa: BLE001 — a router failure keeps the keyword decision
            routed = tier
        # A skipped message that still matches docs keeps an advisory hint.
        tier = routed if routed == "GATE" else ("HINT" if docs else None)
    if tier == "GATE" and kb_config.feature("prompt_gate", kb_root) == "hint":
        tier = "HINT" if docs else None
    if tier is None:
        return
    if tier == "HINT":
        context = ("[KB HINT] This message may touch these knowledge-base docs (relative to "
                   ".claude/knowledge/). If it does, invoke the kb:base skill and read "
                   "them before answering:\n" + "\n".join(f"  {d}" for d in docs))
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": context}}))
        return
    if gate:
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text(json.dumps({"docs": docs}))
    lines = [("[KB MATCH] This message touches the knowledge base. Your FIRST tool call must be the Skill tool "
              "with skill=kb:base; follow its Coverage and reading rules. Read the relevant docs below WHOLE (no "
              "offset/limit), then every relevant doc their reads surface, until nothing new comes up; check claims "
              "about current behaviour against the code. A Stop hook blocks the reply once if this was skipped. "
              "Docs (relative to .claude/knowledge/):")]
    lines += [f"  {d}" for d in docs] or ["  (no doc matched by keyword: check the KB index; if it doesn't cover "
                                          "this, say so and go to the code — see the skill's Coverage section)"]
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}))


def _missing_this_turn(transcript: Path, docs: list[str]) -> list[str]:
    """Unmet requirements since the last user message: skill call, a matched-doc Read."""
    entries = [json.loads(l) for l in transcript.read_text().splitlines() if l.strip()]
    skill = read_match = False
    for e in entries:
        if e.get("type") not in ("user", "assistant") or e.get("isSidechain"):
            continue
        content = e.get("message", {}).get("content")
        # Skill bodies and hook feedback arrive as isMeta user entries, not new turns.
        if e["type"] == "user" and not e.get("isMeta") and (isinstance(content, str) or any(
                b.get("type") == "text" for b in content or [])):
            skill = read_match = False  # new user turn resets
            continue
        for b in content if isinstance(content, list) else []:
            if b.get("type") != "tool_use":
                continue
            inp = b.get("input", {})
            if b.get("name") == "Skill" and _is_kb_skill(inp.get("skill", "")):
                skill = True
            path = inp.get("file_path", "")
            whole = "offset" not in inp and "limit" not in inp
            targets = [f"/.claude/knowledge/{d}" for d in docs]
            if b.get("name") == "Read" and whole and (
                    any(path.endswith(t) for t in targets)
                    if targets else "/.claude/knowledge/" in path):
                read_match = True
    missing = [] if skill else ["invoke the kb:base skill"]
    return missing + ([] if read_match else ["Read the matched docs whole"])


def _stop(payload: dict) -> None:
    if payload.get("stop_hook_active"):
        return
    sid = payload.get("session_id")
    transcript = payload.get("transcript_path")
    if not sid or not transcript:
        return
    gate = _gate_path(sid)
    if not gate.exists():
        return
    docs = json.loads(gate.read_text()).get("docs", [])
    missing = _missing_this_turn(Path(transcript), docs)
    gate.unlink()  # block once per turn; the continuation is not re-gated
    if not missing:
        return
    reason = ("You replied to a KB-associated message without the mandatory KB pause. "
              f"Now: {' and '.join(missing)}, traverse related docs to closure, then "
              "confirm or correct your answer. Matched docs (relative to "
              ".claude/knowledge/): " + ", ".join(docs))
    print(json.dumps({"decision": "block", "reason": reason}))


def _pretool(payload: dict) -> None:
    sid = payload.get("session_id")
    gate = _gate_path(sid) if sid else None
    if not gate or not gate.exists():
        return
    state = json.loads(gate.read_text())
    if state.get("skill"):
        return
    name = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}
    if name == "Skill" and _is_kb_skill(inp.get("skill", "")):
        state["skill"] = True
        gate.write_text(json.dumps(state))
        return
    if name == "Read" and "/.claude/knowledge/" in inp.get("file_path", ""):
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": (
            "KB gate: this message matched the knowledge base. Invoke the Skill tool with "
            "skill=kb:base first, then Read the matched docs whole: "
            + ", ".join(state.get("docs", [])))}}))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if os.getenv("KB_CAPTURE_FORK"):  # background capture forks must not be gated or nudged
        return 0
    if mode == "match":
        tier, docs = classify(" ".join(sys.argv[2:]))
        print(tier or "(no match)")
        print("\n".join(docs))
        return 0
    try:
        payload = json.load(sys.stdin)
        import kb_config
        os.environ.setdefault("KB_ROOT", str(kb_config.session_kb_root(payload)))
        {"prompt": _prompt, "pretool": _pretool, "stop": _stop}[mode](payload)
    except Exception:  # noqa: BLE001 — a hook crash must never block a prompt or stop
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
