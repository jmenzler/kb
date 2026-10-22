---
name: base
description: Consult the project's knowledge base (.claude/knowledge/) before exploring the codebase for conceptual answers — architecture, design rationale, decisions, measured results, status, "how/why does X work" — and for structure questions ("what calls X", "how do A and B connect") via kb-query. Also starts KB setup ("init a KB here", "bootstrap a KB", "add a source"). Not for file lookups, exact-string search or just-do-it edits. Maintenance is /kb:clean, staging a finding is /kb:capture.
---

> Paths below (`scripts/`, `workflows/`, `STYLE.md`) are relative to the plugin root `~/.claude/kb/`.

# Knowledge base

The KB is the project's curated "how everything works" manual: architecture, rationale, decisions, measured
results and how they connect. It is authoritative for what it covers and current-state only.

## First action

If a `<kb-index>` block is in context (injected at session start), use it. Otherwise read
`.claude/knowledge/index.json`. It maps topics to docs (`entries`) and lists extra sources (`sources`).

## Coverage — decide what the index says before reading

| Index says | Do |
|---|---|
| **Covered** | Read the connected tree (below). For claims about *current* behaviour — values, defaults, what the code does now — check the code the doc points to before stating them; if they disagree, the code wins and the doc is stale. |
| **Partly covered** | Read what exists, fill the rest from the code; say which part came from where. |
| **Not covered** | Say so ("the KB doesn't document X") and go straight to the code or another declared source — don't read unrelated docs hoping to find it. |
| **Neither KB nor code answers it** | Say it is an open question, not a guess; it needs research or a decision from the user. |

Gaps the code settles and docs found stale are capture material (`/kb:capture` on request; automatic capture
picks them up at session end). Open questions belong in the project's status/gaps doc if it has one.

## Read the whole connected tree

When the task touches something the KB covers, read the entire connected tree of relevant docs before
answering, planning, editing or writing:

- **Traverse** — matched doc(s) → every relevant doc the `[KB graph]` note lists after a read → theirs, and so
  on; once per seed topic also run `python3 ~/.claude/kb/scripts/kb-query.py explain "<topic>" --docs` to catch
  neighbours without a shared tag. Folder entries: read the folder `index.json`, then the relevant files.
- **Stop at closure** — a pass that surfaces no unread relevant doc. Relevance prunes branches; convenience
  ("already know it", "small edit") never does. This applies every turn a new KB topic appears.
- **Then act** — answers, edits and generated text agree with everything read; if the docs contradict the plan,
  say so first.

Hooks enforce this: a KB-relevant prompt gets a `[KB MATCH]` read list and other tools wait until this skill is
invoked; `??` in a prompt forces the gate. Settings: `python3 ~/.claude/kb/scripts/kb_config.py show`.

## Where to look

| Question | First stop | Fallback |
|---|---|---|
| Architecture, design, rationale, decisions | KB | code search |
| Status, gaps, invariants, rules | KB (`status-*`, `invariants`) | — |
| Measured results, runtime data | KB / declared `sql` source | — |
| Academic theory, derivations | declared `rag` / `notebooklm` source | — |
| What calls / imports X, how A and B connect | `kb-query` (`explain`, `neighbors`, `path`) | code search |
| Why a line or doc is the way it is | `transc why <file> [lines]` (the session that wrote it) | — |
| Known file or symbol, exact string | `Grep` / `Read` — skip this skill | — |

Declared sources render as `<source name tool>` in `<kb-index>`, each with when to use it and how to call it;
if one is unavailable, fall back to the KB or code search. A topic-graph note after a read names related docs:
resolve a name with `python3 ~/.claude/kb/scripts/resolve-file.py <name>`.

```bash
python3 ~/.claude/kb/scripts/kb-query.py explain "X"          # code + doc neighbourhood of X
python3 ~/.claude/kb/scripts/kb-query.py path "A" "B"         # how two things connect
python3 ~/.claude/kb/scripts/kb-query.py query "<concept>"    # explore across both graphs
```

## Setting up and changing a KB

| Want | Read and follow |
|---|---|
| Create a KB here | `workflows/init.md` |
| Build a KB from an existing codebase | `workflows/bootstrap.md` |
| Add, change or remove a data source | `workflows/sources.md` |
| Stage a finding | `/kb:capture` (rules: `workflows/capture.md`) |
| Clean, reconcile the inbox, re-audit | `/kb:clean` |

New knowledge goes to `.claude/knowledge/inbox/` and only `clean` writes it into the KB; small corrections may
be edited in place. Layout rules (index.json, nesting, `sources:` frontmatter): `workflows/format.md`. Writing
style: `STYLE.md`.
