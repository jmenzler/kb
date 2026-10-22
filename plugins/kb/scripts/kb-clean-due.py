#!/usr/bin/env python3
"""Session-start detector: is an (incremental) KB clean due? Arms a Stop-hook ask.

`--full` is NEVER auto-suggested — a full re-audit is a deliberate user action. This only
ever flags the routine, incremental `clean`.

Cheap + FAIL-SILENT — never blocks session start. All thresholds come from `.kb/config.json`
→ `clean` (the dict below is only a fail-silent fallback when the file is absent/partial):

  enabled                 false silences the prompt entirely (default true)
  incremental_threshold   edited-doc count that flags a clean (0 = disable this trigger; default 5)
  review_queue_threshold  code-drift-impacted-doc count that flags a clean (0 = disable; default 1)
  suggest_cooldown_hours  don't re-suggest within this window (default 24)
  mode                    how to run once the USER approves: review | safe | auto (default auto)
  agent_model             model for the (optional, user-approved) background clean agent

Triggers (any one arms the ask):
  - inbox drafts pending reconcile (always on — explicit staged work)
  - >= incremental_threshold docs edited since last clean (content-hash marker)
  - >= review_queue_threshold docs flagged by commits (code drifted under a doc's sources:)
  - never cleaned (no marker yet)

Does NOT print to session context and does NOT consume the cooldown. Instead it writes
`.kb/pending-clean-ask.json` (the authoritative "ask this" state) when due AND past cooldown,
and removes that file otherwise. The Stop hook (`kb-clean-stop.py`) surfaces it once, after
the session's first message, and stamps the cooldown only when the ask is actually delivered.
Called by inject-kb-index.sh.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULTS = {
    "enabled": True,
    "incremental_threshold": 5,
    "review_queue_threshold": 1,
    "suggest_cooldown_hours": 24,
    "mode": "auto",
    "agent_model": "sonnet",
}
SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    sys.path.insert(0, str(SCRIPTS))
    import kb_config
    kb = kb_config.kb_root()
    if not (kb / "index.json").exists():
        return 0
    kbdir = kb / ".kb"
    pending = kbdir / "pending-clean-ask.json"
    if not kb_config.enabled("clean_nudge", kb):
        pending.unlink(missing_ok=True)
        return 0

    cfg = dict(DEFAULTS)
    try:
        loaded = json.loads((kbdir / "config.json").read_text()).get("clean", {})
        if isinstance(loaded, dict):
            cfg.update({k: loaded[k] for k in DEFAULTS if k in loaded})
    except (OSError, json.JSONDecodeError):
        pass

    if not cfg["enabled"]:
        pending.unlink(missing_ok=True)
        return 0

    # Cooldown gate — already nagged recently, so don't re-arm. The stamp is consumed by the
    # Stop hook when it actually delivers the ask, not here on mere detection.
    cooldown_s = float(cfg["suggest_cooldown_hours"]) * 3600
    stamp = kbdir / "last-clean-suggested"
    try:
        if stamp.exists() and (time.time() - stamp.stat().st_mtime) < cooldown_s:
            pending.unlink(missing_ok=True)
            return 0
    except OSError:
        pass

    reasons: list[str] = []

    # 1. Inbox drafts pending reconcile (explicit staged work — always a trigger).
    try:
        drafts = [
            p for p in (kb / "inbox").glob("*.md")
            if p.name != "_TEMPLATE.md"
        ]
        if drafts:
            reasons.append(f"{len(drafts)} inbox draft(s) pending reconcile")
    except OSError:
        pass

    # 2. Changed docs (content-hash marker). "FULL" = no marker yet (never cleaned).
    inc_threshold = int(cfg["incremental_threshold"])
    try:
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "kb-changed.py"), str(kb)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if out == "FULL":
            reasons.append("no clean marker yet (never cleaned)")
        elif out and inc_threshold > 0:
            n = len([ln for ln in out.splitlines() if ln.strip()])
            if n >= inc_threshold:
                reasons.append(f"{n} doc(s) edited since last clean")
    except (OSError, subprocess.SubprocessError):
        pass

    # 3. Review queue — commits whose code touched a doc's sources: (real impacts only).
    rq_threshold = int(cfg["review_queue_threshold"])
    if rq_threshold > 0:
        try:
            rq = (kbdir / "review-queue.md").read_text()
            impacted = [
                ln for ln in rq.splitlines()
                if ln.lstrip().startswith("- ") and "no documented files impacted" not in ln
            ]
            if len(impacted) >= rq_threshold:
                reasons.append(f"{len(impacted)} doc(s) flagged by commits (code drift)")
        except OSError:
            pass

    if not reasons:
        pending.unlink(missing_ok=True)
        return 0

    reason_lines = "\n".join(f"  - {r}" for r in reasons)
    message = (
        "<kb-clean-due>\n"
        "KB clean looks due:\n"
        f"{reason_lines}\n\n"
        "ASK the user whether to run `/kb:clean` now (one short question; don't "
        "auto-run, don't derail their current task). If they say yes, run it per "
        f"`.kb/config.json` clean.mode={cfg['mode']} (review = drafts to inbox only, "
        "safe = apply non-destructive + stage SUPERSEDE, auto = apply auto-confirmable + "
        f"stage SUPERSEDE), optionally as a background subagent (model: {cfg['agent_model']}). "
        "`clean --full` is a separate, deliberate user action — never start one unprompted.\n"
        "</kb-clean-due>"
    )
    try:
        tmp = pending.parent / (pending.name + ".tmp")
        tmp.write_text(json.dumps({
            "created": int(time.time()),
            "reasons": reasons,
            "message": message,
            "fired_sessions": [],
        }))
        tmp.replace(pending)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never block session start
        sys.exit(0)
