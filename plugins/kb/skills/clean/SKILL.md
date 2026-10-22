---
name: clean
description: Incremental KB maintenance — audit and curate the docs changed since the last clean, then reconcile the contribution inbox. Keeps the KB factual, complete, concise, well-connected, current. Owns the shared protocol (checkpoint, reconcile, structure, integrity, coverage, finish) that full-clean reuses. Proposes and applies on confirm. For a whole-KB re-audit + taxonomy redesign, use `--full` (see full-clean.md).
args: "[--auto] [--full]"
---

# kb:clean

Read `~/.claude/kb/workflows/clean.md` and follow it. With `--full` (whole-KB
re-audit + taxonomy redesign) read `workflows/full-clean.md` in the same folder instead. Shared rules: `STYLE.md`
and `TOPIC_GUIDE.md` at the plugin root; agents `kb:clean-reviewer` and `kb:clean-reconciler` ship with this plugin.
