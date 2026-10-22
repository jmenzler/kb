---
name: capture
description: The capture rulebook — stage a contribution into the KB inbox, by hand (manual capture) or from the automatic background fork. Does NOT write to the KB; reconciliation happens in clean.
---

# Workflow: capture

Stage knowledge into `.claude/knowledge/inbox/` so `clean` can later reconcile it into
the KB. Capture never touches the KB itself. There are two paths with different rules:

- **Manual capture** — a user or agent explicitly asks to capture something (this
  workflow, or the `kb:capture` skill's fork). Light: no dedup, no styling.
- **Automatic capture fork** — the background fork started by the capture hook
  (`scripts/kb-capture-hook.py`). Strict: only earned knowledge, deduplicated, fixed body.

Contributors can also drop a raw file into `inbox/` directly.

## Draft format (both paths)

One file per claim at `inbox/YYYY-MM-DD-<short-slug>.md`, frontmatter from `_TEMPLATE.md`:

- `intent`: `add` (new knowledge), `update` (extends something), `correct` (fixes
  something now wrong).
- `captured`: today's date (so `clean` can flag stale contributions).
- `target`: an existing KB doc path if known; else blank — clean will figure out placement.
- `sources`: repo-relative paths/commits the knowledge comes from, if known.

If `inbox/` doesn't exist, create it (`inbox/`, `inbox/processed/`, `_TEMPLATE.md`;
gitignore rule). See `init.md`.

## Manual capture

1. **Take the input** — pasted notes, a file, a session finding, a correction,
   whatever the contributor has. Accept it in whatever form given; don't make them
   format it.
2. **Write one inbox doc** per the draft format. Put the content in the body. Light
   organization is fine (a heading, the facts); do **not** distill, dedup, or rewrite
   into KB style — leave that to clean. Stage even if the KB might already cover it;
   clean NOOPs a redundant draft.
3. **Stop.** Tell the contributor it's staged, and that running `clean` will reconcile
   it into the KB (updating/superseding existing content, applying KB style) and
   archive the inbox doc to `inbox/processed/`.

## Automatic capture fork

The fork has the whole session (or the segment named in its prompt) and decides on its
own what to stage. Its prompt gives the KB path, inbox path, result file and date.

1. **Read** `<kb>/index.json` for the KB's scope.
2. **List candidates** from the conversation. Keep one only if it is **earned**:
   project-specific, AND it took real work in this session — debugging to a confirmed
   root cause, a run or measurement with its numbers, comparing options and settling on
   one, a decision the user made or approved with its reason, or something believed or
   documented shown wrong; OR it is a lasting fact or decision the user stated (date,
   status, constraint, rule).
3. **KB scope.** It must fall within this KB's scope as described in `index.json`;
   knowledge about other projects or general tooling outside that scope is skipped.
4. **Drop**: generic language/library/textbook knowledge; anything that only restates
   what a file, doc, config or command output shows; facts obvious from the repo; task
   progress, status, plans, next steps; drafts of prose; personal preferences about how
   the assistant should work; speculation that was never confirmed.
5. **Dedup.** Search the KB docs and the inbox for each survivor's key terms. Skip it if
   the KB already states it correctly or a draft already covers it. Skip anything a
   `[kb-capture]` note in the conversation says was captured.
6. **Write at most 6 drafts**, one per claim, per the draft format. Body under 50 lines:
   - **Claim** — one or two sentences, stated as current fact. A current config or code value
     (count, threshold, default, list) is named by the file/key that owns it, not copied
     (`STYLE.md` § Point to live values); numbers belong to dated measurements.
   - **Evidence** — the numbers, file:line, commands, commits or user statement that
     establish it.
   - **Why it matters** — the consequence or how to apply it.

   No change logs, file lists of what was edited, or task status.
7. **Write the result file** as JSON:
   `{"drafts": ["<path>", ...], "skipped": [{"claim": "<=15 words", "reason": "generic|lookup|obvious|progress|preference|speculation|out-of-scope|in-kb|in-inbox"}]}`.
   Zero drafts is a normal outcome.

The fork may only read and write drafts and the result file; `kb-capture-guard.py`
denies everything else.

## Do NOT (either path)

- Write to or edit any KB doc, `index.json`, or `topics.json`.
- Apply STYLE.md or reconcile against existing docs (UPDATE / SUPERSEDE). That is
  `clean`'s reconciliation pass.
