---
name: capture
description: Stage a project learning into the KB inbox on explicit request — "capture this", "remember this finding", "add this to the KB", "persist this", "note this for later", "don't lose this", "/kb:capture". Automatic capture needs no invocation: a hook launches a cached background fork at session end, idle (45 min) and before compaction that captures earned knowledge on its own (knowledge-base scripts/kb_capture.py). NOT for — personal preferences (→ auto-memory), task progress (→ scratchpad), transient or self-evident facts. Stages an inbox draft only; reconciliation happens later in clean.
---

> Paths below are relative to the plugin root `~/.claude/kb/`.


# kb-capture

On an explicit request, spawn a **background fork** that stages the learning as a KB inbox draft. The
fork inherits this whole conversation, so it already has the finding, its *why*, and the surrounding
nuance — **you only point it at WHAT to capture; it distils and writes the draft itself**, in its
own context. That keeps the draft mechanics (reading files, verifying paths, composing) out of yours.
Non-blocking — you keep working; `clean` reconciles the draft into the KB later.

**Why a fork, not a named agent:** a named subagent runs cold (can't see this conversation), so you'd
have to distil the nugget yourself and hand it over — then pay spawn overhead just to offload a tiny
file write. A fork (no `subagent_type`) inherits the context for free, so it does the whole capture.

## Steps

1. **KB present?** Check for `.claude/knowledge/index.json` in the project. Absent → do nothing
   (no KB to capture into). Don't derail the current task to offer `init`.
2. **Spawn the fork** — `Agent` with **no `subagent_type`** (this is what makes it a fork that
   inherits context), `name: "kb-capture"`. It runs in the background and returns immediately. Give
   it a tightly-scoped prompt — point it at the canonical protocol rather than restating it (the
   draft shape lives in one place, `capture.md`, so this prompt can't drift from it):

   > Background capture fork. First read `~/.claude/kb/workflows/capture.md` and
   > follow its "Manual capture" section — the draft shape, what to fill, and the rule that you do
   > **not** apply KB style or distil away detail (`clean` does that at reconcile).
   >
   > Then stage ONE inbox draft capturing: **<one-line pointer to the knowledge — e.g. "the root
   > cause we just established for the order-timeout reconcile bug">**. You have the full discussion
   > above; use it for the claim, the *why*, and the files it concerns. Write into
   > `<repo>/.claude/knowledge/inbox/`.
   >
   > Do ONLY this — do not continue the main task, modify code, or touch the KB proper (no doc /
   > `index.json` / `topics.json` edits). Return the draft path.

3. **Notice + continue.** Print one line — `→ captured "<topic>" to KB inbox (reconciles on next clean)` — then resume the task. Do not wait on the fork.

## Notes

- **Don't pre-dedup (manual path).** Stage even if the KB might already cover it; `clean`'s reconcile
  NOOPs a redundant draft. Speed over avoiding the occasional duplicate. The automatic capture fork
  does dedup, per capture.md's "Automatic capture fork" section.
- **One nugget per fork.** Several distinct learnings → several forks, each its own atomic draft.
- **Honor the negatives in the description.** A preference is memory; task progress is scratchpad;
  an obvious/transient fact is nothing. Capture *project knowledge* only.
- **No STYLE.md at capture — by design.** Drafts stay raw; `clean`'s reconcile applies STYLE and
  distils. Two stylers would drift, and a pre-styled/trimmed draft can strip the detail reconcile
  needs to judge UPDATE vs SUPERSEDE vs NOOP against the live KB. `capture.md` is the single source.
