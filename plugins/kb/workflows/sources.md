---
name: sources
description: Manage the per-project data sources in index.json (add/edit/remove) using the uniform {tool, use_for, info} schema. Guided manual editing; surfaced at session start.
---

# Workflow: sources

Manage the `sources` object in the root `index.json` — the per-project data sources
(code search, SQL, RAG, other MCP tools) surfaced at session start as `<source>`
blocks. Guided manual editing; no auto-detection.

Every source uses the uniform three-key schema:

| Key | Holds |
|-----|-------|
| `tool` | Tool name(s) to call, e.g. `mcp__server__tool`. Pipe-separate a related set. |
| `use_for` | One line: when to route here, and when NOT to. |
| `info` | Everything needed to call it — ids, required params/paths, table lists, availability caveats. |

## Built-in universal sources

Two sources need no project-specific setup — their tools are global / ship with the skill,
so any repo can declare them (init seeds both for code-backed KBs; copy the descriptors
from `init.md`'s scaffold):

- **`code_graph`** → `kb-query.py` — traverse the code (AST) + topic-doc graphs: what
  calls X, how A and B connect, a symbol's or doc's neighborhood.
- **`backstory`** → `transc why <file>` — the Claude session that wrote a doc's code: blame
  a doc's `sources:` file → replay the originating session's conversation. Composes with
  every doc's `sources:`.

## Add

Ask the user for: source name (short key, e.g. `sql`, `rag`, `code_search`), the
`tool`, the `use_for`, and the `info`. Insert under `sources` in `index.json`:
```json
"name": { "tool": "...", "use_for": "...", "info": "..." }
```
It auto-appears in `<kb-index>` at the next session start (the converter renders it).

## Edit

Show the existing source, ask which field(s) to change, apply.

## Remove

Confirm, then delete the entry.

## After any change

- Validate `index.json` parses: `python3 -c "import json; json.load(open('.claude/knowledge/index.json'))"`.
- Keep `info` compact — it ships in every session's context.
- Don't invent tool names; use what the user supplies or what's configured in the
  project's MCP setup.
