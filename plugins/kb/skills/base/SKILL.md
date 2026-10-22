---
name: base
description: Check before exploring a project's codebase for conceptual knowledge — architecture, design rationale, theory, empirical data, system status, or "how does X work". Routes the question to the right source: local KB (always), plus any project-declared sources (code search, SQL, RAG, MCP tools) read from the KB index. Also answers STRUCTURE & RELATIONSHIP questions by traversing the KB's two graphs with `kb-query` — what calls/imports X, how two components or docs connect (path), a symbol's or doc's neighborhood — over code (AST) + topic-doc graphs joined by provenance. Project-agnostic — adapts to whatever sources the current repo's `.claude/knowledge/index.json` declares. Also owns KB maintenance workflows (see workflows/): clean (audit + curate + drain/reconcile inbox into the KB, updating not appending), init (bootstrap a KB in a new repo), capture (stage a contribution into the inbox), sources (manage data sources). Triggers: "what calls X", "how do X and Y connect", "what relates to X", "clean the knowledge base", "init a KB here", "add this to the KB", "add a source", "set up knowledge base". NOT for file lookups, exact-string search, or "just do it" edits.
---

> Relative paths below (`scripts/`, `workflows/`, `STYLE.md`, `TOPIC_GUIDE.md`) are relative to the plugin root `~/.claude/kb/`. Maintenance has its own skills: `/kb:clean` (incl. `--full`) and `/kb:capture`.


# Knowledge Base System

A project-agnostic router. The **local KB** mechanism (index + topic graph + scripts) is universal and works in any repo that has `.claude/knowledge/`. **Additional sources** (code search, SQL, RAG, other MCP tools) are declared per-project in the KB index and surfaced at session start — this skill does not hardcode any project's sources.

## FIRST ACTION

If a `<kb-index>` block is already in session context (injected by the session-start hook), use it — skip the read. Otherwise read `.claude/knowledge/index.json` now, before anything else. It gives the topic map (`entries`) and the project's declared sources (`sources`).

## MANDATORY — read the whole connected tree

> **Whenever anything in the chat is mentioned in, or associated with, anything in the KB, STOP. Before answering, planning, editing or writing, read the entire connected tree of relevant KB docs. Only then continue.**

- **Trigger** — any user message, task, file, name, firm, project, concept or decision that matches an `<entry>` description/topic, or that a KB doc you already read points to. Applies every turn, not only the first; a new topic mid-session re-triggers it.
- **Traverse** — read the matched doc(s) → read every doc the `[KB graph]` hook surfaces that bears on the task → for each, repeat → also run `kb-query.py explain "<topic>" --docs` once per seed topic to catch neighbors with no shared tag. Folder entries: read the folder `index.json`, then every relevant file in it.
- **Stop only at closure** — a pass that surfaces no unread doc with relevance to the task. Relevance prunes branches (a doc about an unrelated firm/project is skipped); convenience never does. "I already know this", "the first doc was enough", "it's a small edit" are not stop conditions.
- **Then act** — answers, edits and generated text must agree with everything read. If the tree contradicts the plan, say so before acting.

**Enforced by hooks** (`scripts/kb-prompt-gate.py`): on every user message the `prompt` mode asks `scripts/kb_router.py` whether it needs the KB — a local model (Qwen3-Embedding-0.6B + logistic regression, served warm by `kb-router-daemon.py`, started on demand) decides confident messages and TypeSafe Jev decides the uncertain band, about 30% (measured on real messages: route .90 / skip .86). Jev receives the message, the last ~1,200 chars of the previous assistant turn and a KB summary (index descriptions + doc names); `router: local` keeps everything on the machine; `router: jev` sends every prompt to Jev. Routed messages get the gate described above (a `[KB MATCH]` read list); skipped ones at most a `[KB HINT]`. `??` anywhere in a message forces the gate. With no router answer (daemon down and no Jev key/network, or `router: off`) it falls back to keyword classification: GATE when every word of some doc topic or filename appears in the message, or when a knowledge question (how/why/what/should…, or a `?`) scores against doc topics/filenames/descriptions (≥2 distinct words); a scored non-question gets a `[KB HINT]` only. The `pretool` mode denies every tool except this skill and KB Reads until the skill is invoked; the `stop` mode blocks a reply once if that turn matched but this skill was not invoked or no matched doc was Read whole (no offset/limit). Gate state lives in `~/.claude/kb-gate/<session_id>.json`. Router log: `~/.claude/kb-gate/router-log.jsonl` (first 200 chars per routed message, rotated at 5 MB, written only in repos with a KB and the router on). Debug a miss with `kb-prompt-gate.py match "<message>"`. Only indexes in the `entries` format are matched.

**Automatic capture** (`scripts/kb-capture-hook.py` + `kb_capture.py`, hooks Stop/SessionEnd/PreCompact/UserPromptSubmit): once an interactive session segment has `capture.min_turns` (5) user turns, a background `claude -p --resume <sid> --fork-session` fork on the session's own model (prompt cache reused) reviews it at session end, after `idle_minutes` (45) without a reply, or before compaction, and stages earned-knowledge drafts in the main checkout's inbox, following `workflows/capture.md` "Automatic capture fork". `scripts/kb-capture-guard.py` sandboxes it to Read/Glob/Grep + inbox writes without changing the tool list (that would break the cache). The next prompt gets a one-line `[kb-capture]` note. Log: `~/.claude/kb-gate/capture-log.jsonl`; `daily_soft_cap_usd` (3) only warns. Headless, temp-path and fork sessions never fork. Every hook in `hooks.json` is a no-op inside a fork (`KB_CAPTURE_FORK` switches all `kb_config` features off; the gate, clean-stop and capture hooks also check it directly).

**Switches and install.** Hooks ship with the `kb` plugin (`hooks/hooks.json`) and are on wherever the plugin is enabled (`enabledPlugins` in user or project settings); `python3 scripts/install.py --check` reports missing tools, settings env and leftover duplicate hooks. Per-repo behaviour comes from `scripts/kb_config.py`: env (`KB_HOOKS=off`, `KB_ROUTER`) > `.claude/knowledge/.kb/config.json` > `~/.claude/kb-config.json` > defaults. `features`: `index_inject`, `prompt_gate` (gate|hint|off), `router` (cascade|local|jev|off), `related_docs`, `topic_validation`, `capture`, `clean_nudge`; blocks `router` (band, timeouts), `capture` (thresholds, fork `model`), `jev` (key env var / key file; global only). `kb_config.py show` prints effective values. Details: README "Configuration".

Cheap reads beat confident wrong output: the KB is the source of truth, and facts split across linked docs are exactly what a partial read misses.

## Sources

### 1. Local Knowledge Base (universal)
**Location**: `.claude/knowledge/` → `index.json`
**Contains**: Architecture, components, design rationale, invariants, data flow, status, gaps, file paths — whatever this project documents.
**How to use**: Match query to an entry's description/topics. If the entry has a `folder`, read that folder's `index.json`, then the `.md`. Otherwise read the `.md` directly.

**Topic graph**: after Reading a valuable KB file, a PostToolUse hook injects related files from *other* folders (shared topic tags + 1-hop neighbors). Same-folder docs are excluded — the folder index already lists them. To open a suggested file, resolve its name first:

```bash
python3 ~/.claude/kb/scripts/resolve-file.py <name>
# e.g. resolve-file.py lifecycle      → hedging/lifecycle.md
# e.g. resolve-file.py f/overview     → future-optimizations/overview.md
```

Full topic-system docs: `TOPIC_GUIDE.md`.

### 2. Project-declared sources
The KB index's `sources` object lists every extra source for this project, each with a uniform `{tool, use_for, info}` shape. They are pre-rendered at session start as `<source name="..." tool="...">use_for + info</source>` inside `<kb-index>`. Read those to know what's available, then route per `use_for`. If `<kb-index>` is not present, read the `sources` object from `index.json`.

Each `<source>` carries its own `use_for` (when to route there) and `info` (how to
call it) — read those at session start, no fixed catalog here. A source may note it can
be unavailable (e.g. an MCP server that isn't running); if a call fails, fall back to
the local KB or code search.

## When NOT to use this skill

Skip it for tasks that need no conceptual project knowledge:

- **File lookup**: "Where is the portfolio code?" → `Glob`/`Grep`
- **Specific read**: "Show me the OMS" → `Read` the file
- **Exact-string search**: "Find all uses of `client_order_id`" → `Grep`
- **Just-do-it edits**: "Fix this test" / "Add a field to Order" → do it

**Use it when** the question is about *understanding* — architecture, theory, design rationale, empirical data, system status, "how does X work" — **or about structure/relationships** ("what calls X", "how do A and B connect", a component's or doc's neighborhood) → `kb-query`. Boundary: a *textual* "find all occurrences of `foo`" is still `Grep`; "what **calls** `foo` / how is it **wired**" is `kb-query`.

## Routing

Decide source by question type, not habit. Local KB is the default first stop for any "understanding" question; the rest are fallbacks or specialized.

| Question type | First stop | Fallback |
|---------------|-----------|----------|
| Architecture / design / wiring | Local KB | `code_search` |
| Component implementation | Local KB (`components/`) | `code_search` |
| Strategy / theory / math (project's own) | Local KB (`strategy/`) | `rag`/`notebooklm` |
| Academic framework / derivation | `rag`/`notebooklm` | — |
| Empirical / runtime data | `sql` | Local KB |
| Implementation status / gaps | Local KB (`status-*.md`) | — |
| Invariants / rules | Local KB (`invariants.md`) | — |
| File location (known symbol/name) | `Grep`/`Glob` | `code_search` |
| Vague "where do we do X" | `code_search` | Local KB |
| Exact string | `Grep` | — |
| **What calls/imports X · a symbol's neighborhood** | **`kb-query` (`--ast`)** | `code_search` |
| **What docs relate to X · its conceptual neighbors** | **`kb-query` (`--docs`)** | Local KB |
| **How do A and B connect (path)** | **`kb-query path`** | — |
| **Background from the session that wrote X / reasoning behind a line** | **`backstory`** (`transc why <doc's sources: file>`) | — |

Decision shortcut:
- Know the **symbol/file** → `Grep`/`Read` (skip this skill).
- Know the **concept, not the location** → `code_search`.
- Want **why / how-designed / what-status** → Local KB.
- Want **what's connected to X / how A and B relate / a neighborhood** → `kb-query` (see below).
- Want **formal theory / a derivation** → `rag`/`notebooklm`.
- Want **numbers from live/historical data** → `sql`.

## Graph queries — `kb-query` (built-in: code + topic graphs)

Beyond *reading* docs, you can **traverse** the KB's two graphs with one tool. Reach for it
whenever the question is about **relationships or structure**, not one doc's prose:

| Ask | Command |
|-----|---------|
| What does X call / its code neighborhood | `kb-query.py explain "X" --ast` · `neighbors "X" --ast` |
| What docs relate to X / its conceptual neighbors | `kb-query.py explain "X" --docs` |
| How do A and B connect | `kb-query.py path "A" "B"` |
| Explore a concept across code + docs | `kb-query.py query "<concept>" [--dfs]` |

```bash
python3 ~/.claude/kb/scripts/kb-query.py explain "OMS"
```
Default spans **both** graphs (sectioned CODE / DOCS), joined by `sources:` provenance — a
code symbol shows its documenting doc; a doc shows its documented symbols + shared-topic
neighbors. `--ast` / `--docs` scope to one layer (topic layer works even with no AST graph).
Faster than grepping for "what's connected to X". (Declared per-project as the `code_graph`
source, so it also appears in `<kb-index>`.)

## Backstory — `backstory` (`transc why`)

`kb-query`/docs answer **what** and **how it's structured**; `backstory` replays the
**Claude session that wrote** a line or doc — its reasoning and the decisions around it,
beyond what the doc or commit message carries. Follow a doc's `sources:` into history:

```bash
transc why src/trading/risk/impl.py 40-72     # → the session that wrote those lines
```
Claude-authored commits replay the session conversation; human/older commits show the commit
summary only. Declared as the `backstory` source (in `<kb-index>`); composes with the
`sources:` every doc already carries — nothing stored per-doc.

## Workflows

Maintenance procedures live in `workflows/`. When a task matches, **read the file
and follow it** — don't inline the steps here. They share the `scripts/` below.

| Want | Trigger | Read |
|------|---------|------|
| Incremental audit/curate; reconcile the inbox | "clean the KB", "fix/tidy the knowledge base" (no `--full`) | `workflows/clean.md` |
| Whole-KB re-audit + taxonomy redesign | "clean --full", "full clean", "re-audit the whole KB" | `workflows/full-clean.md` |
| Stand up a KB in a new repo | "init a KB here", "set up knowledge base" | `workflows/init.md` |
| Bootstrap a KB for an existing codebase | "bootstrap a KB", "build a KB from this codebase" | `workflows/bootstrap.md` |
| Stage a contribution into the inbox | "add this to the KB", "capture this" | `workflows/capture.md` "Manual capture" (the `kb:capture` skill runs it in a fork on explicit request; automatic capture is the hook above) |
| Add/change/remove a data source | "add a source", "wire up X to the KB" | `workflows/sources.md` |

**bootstrap vs clean** (a common mix-up): `bootstrap` *creates* content from a codebase
that has no docs yet — AST skeleton + harvested prose → atomic docs. `clean` *curates
docs that already exist* (reshape, reconcile inbox, integrity, graph). On an empty KB,
`clean` is a no-op; run `bootstrap`. They aren't alternatives — `bootstrap` ends by
running `full-clean` to settle the docs it just wrote.

**Contributing knowledge (inbox):** anyone drops content into `.claude/knowledge/inbox/`
— a raw file, or a tidy doc via `capture` (or a filled `inbox/_TEMPLATE.md`), in any
form. `clean` then **reconciles** the inbox into the KB (analyze → ADD/UPDATE/SUPERSEDE
→ write in style) and archives processed docs to `inbox/processed/`. The inbox is
gitignored (staging only); the reconciled KB is what's committed. **Staging never
writes to the KB — only `clean` does.**

**What the KB is** — a *"how everything works"* manual, not a code manual. Its heart is
the **conceptual relationships between docs** (how components, theory, and decisions fit
together) — most of which have no code edge. Code/AST signals supplement; they never
replace the conceptual map.

**Core principle — the KB is authoritative and current-state-only.** Reads are gospel:
no "provisional/draft" hedging. Reconciliation *updates and supersedes* — stale or
contradicted content is rewritten or deleted, never left beside the new. The KB stays
factual, complete, concise; it does not grow unbounded. Writing style: `STYLE.md`.

### Maintenance scripts (shared by workflows)
```bash
# Integrity + staleness report (read-only). Finds files from project root via fd.
python3 ~/.claude/kb/scripts/kb-doctor.py [kb_root]
#   orphaned docs · dangling folder/supp refs · dead vs stale code refs ·
#   broken provenance (sources: path gone) · long files >400 lines · topic drift

# Whole-KB connectivity: hubs (degree), isolated docs, islands, over-broad hub topics.
python3 ~/.claude/kb/scripts/kb-graph-full.py [kb_root] [--json|--mermaid]

# Self-audit (read-only): coverage (undocumented central code, ranked + %) + drift
#   (docs whose sources: code moved since updated:, with named symbol delta).
python3 ~/.claude/kb/scripts/kb-coverage.py [kb_root] [--json]
# Commit-time impact: append docs a commit may stale → .kb/review-queue.md (run by hook).
python3 ~/.claude/kb/scripts/kb-review-queue.py [kb_root] [--commit <ref>]

# Export KB as an Obsidian vault (docs + wikilink graph + tags) → <repo>/kb-vault/.
# First run inits the vault; the post-commit hook then keeps it fresh while it exists.
python3 ~/.claude/kb/scripts/kb-obsidian.py [kb_root] [--out <dir>]

# Incremental clean scope: KB docs changed since last clean (or "FULL" if no marker).
python3 ~/.claude/kb/scripts/kb-changed.py [kb_root] [--mark]

# Deterministic AST skeleton of a codebase (graphify/tree-sitter) — digest + --out graph.
python3 ~/.claude/kb/scripts/kb-ast.py <code_root> [--out .kb/ast-graph.json]
# AST-implied doc links: doc pairs whose sources call/import each other but share no topic.
python3 ~/.claude/kb/scripts/kb-ast-links.py [kb_root]
# Query BOTH graphs (zero-dep): query/path/explain/neighbors over code (AST) + topic docs.
python3 ~/.claude/kb/scripts/kb-query.py query "<q>" [--dfs|--ast|--docs]
```

**`.kbignore`** lists what the graph/doctor/related-hook ignore (gitignore-style).
**`.kb/`** holds local machinery (caches, markers, backups) — gitignored. Both are set
up by `init`/`clean`; routing doesn't need their internals.

---

## index.json Format Standard

Flat, routing-first structure. Descriptions do the heavy lifting; topics are keyword fallback.

### Root index.json
```json
{
  "description": "One-line purpose of this KB",
  "entries": {
    "folder-name": { "folder": "folder-name/", "description": "...", "topics": ["categorical"] },
    "filename.md": { "description": "...", "topics": ["specific", "keywords"] }
  },
  "sources": {
    "source-name": { "tool": "...", "use_for": "when to route here", "info": "ids, paths, tables, caveats" }
  },
  "supplementary_docs": {
    "name": { "file": "../path/to/external.md", "description": "..." }
  }
}
```

### Folder index.json
```json
{
  "description": "One-line purpose of this folder",
  "files": { "filename.md": { "description": "...", "topics": ["specific"] } },
  "entries": { "sub-name": { "folder": "sub-name/", "description": "...", "topics": ["categorical"] } }
}
```

`entries` is optional and only needed when a folder holds sub-folders. It uses exactly
the root index's shape, so nesting is the same construct at every level: `folder` is
relative to the index's own directory, and a folder index may itself declare further
sub-folders — depth is unbounded. Flat KBs (no `entries` in any folder index) are
unaffected.

**Nesting semantics**

| Aspect | Rule |
|--------|------|
| Doc paths | Always KB-root-relative — a doc two levels down is `findings/recovery/hazard-curve.md` |
| Topic inheritance | A doc carries its own topics plus the categorical topics of **every** ancestor folder, composed down the chain |
| Edges | Still file-level topics only (folder tags would make each folder a clique) |
| Folder groups | A nested doc is a member of its immediate folder **and** every ancestor — membership mirrors inheritance |
| Cycles / escapes | A folder entry pointing at an ancestor, itself, or outside the KB root raises loudly; it is never silently skipped |
| Flat compatibility | A folder index with only `files` behaves exactly as before |

### Sources schema (uniform)
Every entry under `sources` uses exactly three keys:

| Key | Holds |
|-----|-------|
| `tool` | The tool name(s) to call (e.g. `mcp__server__tool`). Pipe-separate a related set. |
| `use_for` | One line: when to route here, and when NOT to. |
| `info` | Everything needed to call it — ids, required params/paths, table list, availability caveats. |

The session-start converter renders each as `<source name tool>use_for info</source>`. Keep `info` compact — it ships in every session.

### Guidelines

| Rule | Why |
|------|-----|
| 5-8 topics max per entry | More is noise; descriptions carry routing |
| Folder topics = categorical | e.g. "market_making_strategies" |
| File topics = specific | e.g. "VPIN", "avellaneda_stoikov" |
| Descriptions primary, topics fallback | AI matches description first |
| **Descriptions name the QUESTION, not the answer** | Routing contract + folder exclusions: `STYLE.md` |

### Doc frontmatter (provenance)
Every KB `.md` may carry a leading frontmatter block recording what it derives from:
```markdown
---
sources:
  - src/trading/core/oms.py
  - docs/order-lifecycle.md
  - commit:a1b2c3d
updated: 2026-05-21
---
```
`sources` is repo-relative paths (or `commit:<hash>` / URLs). It powers staleness
detection (`kb-doctor` flags a doc when a `sources` path is gone) and lets `clean`
find which doc to UPDATE when reconciling the inbox. `clean` populates it; keep it
current when editing a doc.

### Adding content
**New file in existing folder:** create `.claude/knowledge/<folder>/<topic>.md`, add an entry to `<folder>/index.json`.
**New folder:** create the dir + `<folder>/index.json` (folder format), add a folder entry to root `index.json`.
**New sub-folder:** same, but the folder entry goes in the *parent* folder's `index.json` under `entries`, with `folder` relative to that parent.
**New source:** add a `{tool, use_for, info}` entry under root `sources`. It auto-appears at next session start.
