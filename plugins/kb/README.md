# Knowledge Base

A project-agnostic knowledge system for Claude Code. It is two things at once: a
**router** that points a question at the right source of truth, and a **maintenance
toolkit** that keeps a project's knowledge base factual, connected, and current —
including a self-auditing layer that knows what the KB is *missing* and what has gone
*stale*.

## Purpose

Codebases answer "what does this code do." They are bad at answering "why is it built
this way," "how do these pieces fit together," "what's the theory behind this
strategy," "what's the current status," "what are the invariants." That conceptual
knowledge lives in a per-project knowledge base at `.claude/knowledge/`, and this skill
is how Claude finds it, routes around it, and maintains it.

The mechanism (index + topic graph + scripts + hooks) is universal — it works in any
repo that has a `.claude/knowledge/` directory. Everything project-specific (which
extra sources exist, what topics matter) is declared *in the KB itself*, not hardcoded
here.

---

## How it works

The KB is a folder of atomic Markdown docs plus `index.json` routing files. On top of
the docs sit **three fused assets**:

1. **Conceptual doc graph** — docs connected by shared topic tags. This is the heart:
   the "why" and "how it fits together." Most edges have no code behind them
   (theory → strategy, design rationale, invariants, cross-cutting concerns).
2. **AST code graph** — a ground-truth `tree-sitter` extraction of the codebase
   (symbols, calls, imports), kept fresh by a post-commit hook at
   `.kb/ast-graph.json`. This is the "what," and it only *supplements* the doc graph.
3. **Provenance bridge** — docs declare which source files they describe via a
   `sources:` frontmatter field, joining the two graphs.

Fusing these is what lets the KB audit itself (see [Self-auditing](#self-auditing)).

**Core principle:** the KB is *authoritative and current-state-only*. Reads are gospel —
no "provisional/draft" hedging. New knowledge **updates and supersedes**; stale content
is rewritten or deleted, never left beside the new. The KB does not grow unbounded.

---

## Routing — the first job

When a question is about *understanding* (not a file lookup), the skill picks a source:

| Question type | First stop | Fallback |
|---------------|-----------|----------|
| Architecture / design / wiring | Local KB | `code_search` |
| Component implementation | Local KB | `code_search` |
| Strategy / theory / math (project's own) | Local KB | `rag` / `notebooklm` |
| Academic framework / derivation | `rag` / `notebooklm` | — |
| Empirical / runtime data | `sql` | Local KB |
| Status / gaps / invariants | Local KB | — |
| File location (known symbol) | `Grep` / `Glob` | `code_search` |
| Exact string | `Grep` | — |

The local KB is always available. **Additional sources** (code search, SQL, RAG, other
MCP tools) are declared per-project in `index.json`'s `sources` object — each with a
`{tool, use_for, info}` shape — and surfaced at session start. The skill does not
hardcode any project's sources; it reads what the repo declares.

**It deliberately stays out of the way** for file lookups, exact-string search, and
just-do-it edits — those need no conceptual knowledge.

---

## Maintenance — the second job

Procedures live in `workflows/`. Each is a Markdown playbook the skill reads and
follows; they share the scripts below.

| Workflow | What it does |
|----------|--------------|
| `init.md` | Stand up a fresh KB in a repo: scaffolds `index.json`, `topics.json`, `.kbignore`, `inbox/`, template, `.kb/config.json`; checks the global hooks (`install.py --check`); installs the AST post-commit hook. |
| `bootstrap.md` | Build a KB *from an existing codebase*: AST digest → read code at god-nodes/clusters → draft atomic docs with provenance → `full-clean`. |
| `capture.md` | The capture rulebook: manual staging into `inbox/`, and the rules the automatic capture fork follows. Writes nothing to the KB. |
| `clean.md` | The workhorse. Incremental audit, curate, and reconcile (the changed set) — see below. Owns the shared protocol. |
| `full-clean.md` | Whole-KB re-audit (`clean --full`): parallel fan-out over every doc + taxonomy redesign. Thin superset of `clean.md`. |
| `sources.md` | Add / edit / remove a project data source in the index. |

### The contribution flow

Anyone drops content into `.claude/knowledge/inbox/` — a raw note, or a tidy doc via
`capture`. The inbox is gitignored (staging only). **Staging never writes to the KB.**
Only `clean` reconciles the inbox into the KB, then archives processed files to
`inbox/processed/`.

### `clean` — four stages

`clean` runs **PLAN → REVIEW → INTEGRATE → VERIFY**:

1. **Plan** (`--full`) — survey the structure, partition the KB into *semantic* sections,
   assign one parallel subagent per section.
2. **Review → inbox** — checkpoint (git), then a parallel **fan-out**: each subagent reads
   its KB section + the code it documents + the **narrative history** around it, and writes
   **delta drafts** into the inbox (corrections, additions, provenance). Read-only on the
   KB — the inbox is clean's work buffer and the orchestrator never loads doc bodies. This
   is the `bootstrap` pattern turned inward.
3. **Integrate → KB** — reconcile the inbox (the single write path): each claim classified
   **ADD / UPDATE / SUPERSEDE / NOOP** (UPDATE when new and old coexist; SUPERSEDE only when
   they can't — always confirmed, even under `--auto`; removed text backed up to
   `.kb/superseded/`). Then reshape structure (folders/splits/merges; AST informs, never
   overrides a conceptual relationship).
4. **Verify** — integrity (`kb-doctor`), self-audit (`kb-coverage`: coverage gaps + drift +
   drain the review queue), connections (isolated docs, islands, over-broad hub topics;
   fan-out `MISSING-LINK` is primary, AST-implied links a *filtered* catch-net — import
   edges are mostly noise).

Style (`STYLE.md`) is applied at write time throughout, never a separate pass. Scope is
incremental by default (`kb-changed.py` marks what changed since the last clean); `--full`
re-audits every doc via the fan-out and is a **deliberate user action**, never auto-run.

**Narrative tier — the *why* behind the *what*.** `full-clean` also mines the repo's
process records — `bugs/`, `hypothesis/` (`VERIFIED`/`REFUTED` verdicts),
`implemented-plans/`, and `scratchpad/` TL;DRs — distilling durable lessons (a refuted
"don't do X because Y", a decision rationale, a root-cause gotcha) into KB prose. They're
harvest *input*, never ingested verbatim; current-state-only holds.

### Suggesting a clean — armed at session start, asked after the first reply

At SessionStart, `kb-clean-due.py` (cheap, fail-silent) checks whether an **incremental**
clean is due — inbox drafts pending, ≥`incremental_threshold` docs edited,
≥`review_queue_threshold` commit-flagged code-drift docs, or never cleaned. If so, and the
cooldown has passed, it arms `.kb/pending-clean-ask.json`. The Stop hook `kb-clean-stop.py`
delivers that once per session, as a block after the first reply that tells the assistant
to **ask the user** whether to run `clean` (never auto-runs). Thresholds and cooldown live in
`.kb/config.json`'s `clean` block; `clean.mode` and `clean.agent_model` only change the
wording of the ask. `features.clean_nudge: false` (or legacy `clean.enabled: false`)
silences it. `full-clean` is never auto-suggested.

---

## Self-auditing

The payoff of fusing the doc graph, AST graph, and provenance bridge. Three signals,
surfaced during `clean` and at commit time.

### Coverage — what the KB is *missing*

`kb-coverage.py` intersects the most central code (AST god-nodes / high-degree symbols)
with doc provenance. Central code that **no doc cites** is a ranked gap; it reports a
coverage percentage and the top undocumented hubs with their key symbols. It also flags
*low-signal* docs whose sources are all peripheral.

> Coverage gaps are **SUGGESTIONS** — centrality is not the same as doc-worthiness, so
> the agent judges. `clean` never auto-creates docs from them.

### Drift — what has gone *stale*

For each doc carrying `sources:` **and** `updated:`, the script checks whether those
source files changed since the doc's `updated:` date (via git), and **names the
structural delta** — e.g. *"engine.py gained `reserve_capital()`, dropped `_old_calc()`
since updated: → REVIEW."* The current AST cross-checks the diff to drop false
positives. Because the AST graph is a single snapshot, drift uses git history, not a
historical graph.

> Drift items are flagged for **REVIEW, never auto-rewritten.** `clean` treats them
> like broken provenance: verify against live code, reconcile, refresh `updated:`.

### Review queue — staleness surfaced *at commit time*

`kb-review-queue.py` runs from the post-commit hook (after the AST refresh, so it sees
the fresh graph). It maps a commit's touched code files plus their 1-hop AST
callers/callees to the docs that cite them, and appends a capped block to
`.kb/review-queue.md`:

```
## 54131071 fix(helius): use as_pool(event.venue) — 2026-05-21
- invariants.md ← portfolio.py (touched)
- risk.md ← risk/engine.py (caller of reserve_capital())
```

`clean` folds the queue into its deep-read scope, resolves the entries, and clears it.
The KB tells you what to re-read *when the code changes*, not months later.

---

## Obsidian view

`kb-obsidian.py` exports the KB as a browsable [Obsidian](https://obsidian.md) vault.
Obsidian's graph view is built from inline `[[wikilinks]]` and `#tags`, which the KB
doesn't carry (its edges live in `index.json` and the AST graph) — so the exporter
mirrors every doc into `<repo>/kb-vault/` and **materialises those edges**: each note
gets `tags:` from its topics and a `## Related` section of wikilinks (topic neighbors +
AST-implied code neighbors), plus a `_graph.md` mermaid overview. Open that folder
directly as a vault and the graph/tag panes light up. (It lives at the repo root, not
under `.claude/.../.kb/`, because Obsidian's folder picker hides dot-folders —
`kb-vault/` is reachable and should be git-ignored.)

**Groups (colored clusters).** Docs are grouped by their KB folder. Each note carries a
`#group/<folder>` tag, the exporter writes `.obsidian/graph.json` with a color group per
folder, and a `_group-<folder>.md` hub note links the group's members (and cross-links
to connected groups). The graph view then shows colored clusters around group hubs —
the same approach graphify uses for its community vaults.

The vault is generated and disposable — edits there are overwritten; curate the real
KB. It's **config-driven** via `.kb/config.json` `obsidian` (`enabled`, `path` — default
`kb-vault`): the first `kb-obsidian.py` run creates it at `path` and flips `enabled` true,
and the post-commit hook regenerates it on later commits *only when enabled* (a pre-config
vault dir still counts, for back-compat), so it costs nothing until you turn it on.

---

## Scripts

All under `scripts/`. The KB graphs are plain JSON built from the index files and the AST,
with no vector store; only the prompt router loads a local embedding model.

**Hooks and their helpers**

| Script | Purpose |
|--------|---------|
| `hooks.json` | Canonical hook registrations; `install.py` merges them into `~/.claude/settings.json`. |
| `install.py` | Installer: merges `hooks.json` (backup, idempotent), sets `CLAUDE_CODE_FORK_SUBAGENT=1`; `--check` reports missing hooks and tools. |
| `kb_config.py` | The switchboard: layered config, feature flags and the single KB-root resolver for every hook. `show [dir]` prints effective values with their source. |
| `inject-kb-index.sh` | SessionStart: injects `<kb-index>`, then runs `kb-clean-due.py`. |
| `kb_index_to_xml.py` | Renders `index.json` (entries + sources) as the `<kb-index>` block. |
| `kb-prompt-gate.py` | The read gate: `prompt` (route the message, arm the gate), `pretool` (deny other tools until the skill runs), `stop` (block a reply that skipped the reads). `match "<msg>"` debugs keyword matching. |
| `kb_router.py` | Decides whether a message needs the KB: local model, Jev for the uncertain band. |
| `kb-router-daemon.py` | Keeps Qwen3-Embedding loaded behind a Unix socket; started on demand, exits after 2 h idle. |
| `kb-router-local.json`, `kb-router.json` | Router configs (local cutoff/band, Jev combiner, context sizes), fitted offline on labelled chat messages (the evaluation harness is not part of the plugin). |
| `show-related.py` | PostToolUse(Read): after a KB doc is read, injects related docs from other folders. |
| `validate-topics.py` | PreToolUse(Write\|Edit): denies KB index writes with topics not registered in `topics.json`. |
| `kb-clean-due.py` | Detects a due incremental clean and arms `.kb/pending-clean-ask.json`. Reads `.kb/config.json` `clean`. |
| `kb-clean-stop.py` | Stop: delivers the armed clean ask once per session. |
| `kb-capture-hook.py` | Capture hook entry (stop, session-end, precompact, prompt) plus the detached idle timer and fork runner. |
| `kb_capture.py` | Capture logic: when a fork is due, the fork command, result handling, notes, log, sweep. |
| `kb-capture-fork-prompt.md` | The prompt given to the capture fork; points it at `workflows/capture.md`. |
| `kb-capture-guard.py` | PreToolUse sandbox inside the fork: Read/Glob/Grep anywhere, Write only to the inbox and result dir. |

**Maintenance and graph tools**

| Script | Purpose |
|--------|---------|
| `kb_graph.py` | Topic-tag graph from `index.json` files. The shared module for related/files-for/topics/check. |
| `kb_ast_lib.py` | Shared AST helpers: `Graph`, graph loader, frontmatter parsers, the doc↔file provenance join, centrality. One canonical home reused by the tools below. |
| `kb-doctor.py` | Integrity + staleness report (read-only): orphans, dangling refs, dead/moved code refs, broken provenance, long files, topic drift. |
| `kb-graph-full.py` | Whole-KB connectivity: degree hubs, isolated docs, islands, over-broad hub topics. |
| `kb-coverage.py` | Self-audit: coverage (gaps + %) and drift (symbol-delta since `updated:`). `--json`. |
| `kb-review-queue.py` | Commit-time impact → `.kb/review-queue.md`. |
| `kb-obsidian.py` | Export the KB as an Obsidian vault (docs + wikilink graph + tags) → `obsidian.path` (default `<repo>/kb-vault/`); sets `obsidian.enabled` in config. |
| `kb-ast.py` | Deterministic AST skeleton via `graphify`/tree-sitter — digest + `--out` graph. |
| `kb-query.py` | Zero-dependency traversal of **both** graphs — code (AST) + topic docs, joined by `sources:` provenance: `query` / `path` / `explain` / `neighbors`; `--ast` / `--docs` to scope to one layer. |
| `kb-ast-links.py` | AST-implied doc links: doc pairs whose sources call/import each other but share no topic. |
| `kb-changed.py` | Incremental clean scope — docs changed since the last clean (content-hash marker). |
| `resolve-file.py` | Resolve a basename / disambiguated name to a full KB-relative path. |
| `kb-ast-refresh.sh` | Post-commit hook logic: rebuild the AST graph + update the review queue on code commits. |
| `install-ast-hook.sh` | Idempotent, worktree-safe installer for the post-commit hook. |

---

## Conventions

- **Provenance frontmatter** — docs declare what they describe:
  ```markdown
  ---
  sources:
    - trading/core/portfolio.py
    - trading/core/reconciliation.py
  updated: 2026-05-21
  ---
  ```
  `sources:` powers coverage, drift, links, and broken-provenance detection.
  `updated:` enables drift tracking.
- **`.kbignore`** — the single source of truth for what the graph/doctor/hooks ignore
  (gitignore-style globs). No hardcoded defaults. Baseline:
  `knowledge-graph graphify-out inbox .kb`.
- **`.kb/`** — all local machinery (AST cache, AST graph, clean marker, superseded
  backups, review queue). Gitignored and in the `.kbignore` baseline.
- **`index.json`** — flat, routing-first. Root entries map to files or folders;
  descriptions do the routing, topics are the keyword fallback; `sources` declares the
  project's extra data sources.

---

## Install

This folder is the `kb` Claude Code plugin: skills `kb:base`, `kb:capture`, `kb:clean`; agents
`kb:clean-reviewer`, `kb:clean-reconciler`; every hook in `hooks/hooks.json`. Needs `python3` ≥ 3.9 and `git`;
everything else is optional and degrades gracefully.

```bash
# any machine (in Claude Code: /plugin install kb --marketplace jmenzler/kb)
claude plugin marketplace add jmenzler/kb
claude plugin install kb@kb-marketplace

# development: load the working copy in place instead (edits are live next session or after /reload-plugins)
ln -s <repo>/plugins/kb ~/.claude/skills/kb      # loads as kb@skills-dir

# then, once
python3 ~/.claude/kb/scripts/install.py           # sets env, removes legacy settings hooks, checks tools
```

At every session start the plugin points `~/.claude/kb` at its own install folder, so docs, KB index sources
and commands can use `~/.claude/kb/scripts/…` wherever the plugin is installed (`~/.claude/kb` exists after the
first session). `install.py` sets `env.CLAUDE_CODE_FORK_SUBAGENT=1` (plugins cannot set env; manual `kb:capture`
needs it to fork with the conversation) and removes old KB hook registrations from `~/.claude/settings.json`
(they would run twice). Disable the whole plugin with `claude plugin disable kb@kb-marketplace` (or
`kb@skills-dir`), single features with the switchboard below.
`--check` reports missing hooks and tools. Required: `uv` (router daemon), `claude`
(capture forks), `git` (KB root). Optional: `graphify` (code graph), `transc` (backstory
source), a TypeSafe key in `$TYPESAFE_API_KEY` or `~/.config/typesafe/api_key` (Jev; without it the router stays
local), `/usr/share/dict/words` (without it the keyword fallback has no jargon signal).

---

## Hooks (global)

All hooks are registered globally from `scripts/hooks.json` and decide per repo through
`kb_config.py`: a directory without a KB, or with the feature switched off, does nothing.

| Event | Script | Feature | What it does |
|-------|--------|---------|--------------|
| SessionStart | `inject-kb-index.sh` | `index_inject` | Injects the KB index + declared sources as `<kb-index>`; then runs `kb-clean-due.py`, which arms a clean ask when one is due (`clean_nudge`). |
| UserPromptSubmit | `kb-prompt-gate.py prompt` | `prompt_gate`, `router` | Routes the message (see below). A routed message gets a `[KB MATCH]` read list and arms a per-session gate; a near miss gets an advisory `[KB HINT]`. |
| PreToolUse | `kb-prompt-gate.py pretool` | `prompt_gate` | While the gate is armed, denies every tool except the skill and KB Reads until the skill is invoked. |
| Stop | `kb-prompt-gate.py stop` | `prompt_gate` | Blocks a reply once if the turn was gated but the skill was not invoked or no matched doc was Read whole. |
| PreToolUse(Write\|Edit) | `validate-topics.py` | `topic_validation` | Denies KB index writes with topics not registered in `topics.json`. |
| PostToolUse(Read) | `show-related.py` | `related_docs` | After a KB doc is read, injects related docs from other folders (shared topics, `related_hops` deep). |
| Stop | `kb-clean-stop.py` | `clean_nudge` | Delivers the armed clean ask once, after the session's first reply. |
| Stop, SessionEnd, PreCompact, UserPromptSubmit | `kb-capture-hook.py` | `capture` | Automatic capture (see below). |
| post-commit (per repo) | `kb-ast-refresh.sh` | — | On a code-touching commit, rebuilds the AST graph and refreshes the review queue in the background; regenerates the Obsidian vault when `obsidian.enabled`. Installed by `install-ast-hook.sh`. |

Every hook in `hooks.json` is a no-op inside a capture fork: `KB_CAPTURE_FORK` switches all `kb_config` features off, and the gate, clean-stop and capture hooks also check it directly.

**Router.** `kb_router.py` asks a local model (Qwen3-Embedding-0.6B + logistic regression,
kept warm by `kb-router-daemon.py`) whether the message needs the KB. Confident scores
decide locally; the uncertain band (about 30% of messages) goes to TypeSafe Jev. With no
router answer it falls back to keyword matching against doc topics, filenames and
descriptions. `??` anywhere in a message forces the gate without asking the router.
Decisions go to `~/.claude/kb-gate/router-log.jsonl` (first 200 characters of each routed
message, rotated at 5 MB; written only in repos with a KB and the router on).

**Privacy.** For messages in the uncertain band, `api.typesafe.ai` receives the user
message, the last ~1,200 characters of the previous assistant turn, and a KB summary
(index descriptions and doc names). `router: "local"` keeps everything on the machine;
`router: "off"` uses keywords only and never starts the daemon.

**Automatic capture.** Once a session segment has `min_turns` user turns, a background
`claude -p --resume <sid> --fork-session` fork on the session's own model (reusing its
prompt cache) reviews it at session end, after `idle_minutes` without a reply, or before
compaction (from a transcript copy). Session-end and idle forks are skipped once the cache
is cold (`cold_minutes`), and no fork starts while the inbox holds `inbox_cap` drafts.
The fork follows `workflows/capture.md` and stages drafts in the main checkout's inbox;
`kb-capture-guard.py` limits it to reads plus writes to the inbox. The next prompt gets a
one-line `[kb-capture]` note, with a warning once the day's forks cost more than
`daily_soft_cap_usd`. Headless, temp-path and fork sessions never fork. Log:
`~/.claude/kb-gate/capture-log.jsonl`.

---

## Configuration

`scripts/kb_config.py` is the switchboard every hook reads. Layers, highest wins:

1. env — `KB_HOOKS=off` (everything off), `KB_ROUTER=cascade|local|jev|off`, `KB_CAPTURE_FORK` (set inside capture forks: everything off)
2. repo — `.claude/knowledge/.kb/config.json`
3. global — `~/.claude/kb-config.json`
4. built-in defaults

Every key is optional. Defaults:

```json
{
  "features": {
    "index_inject": true,
    "prompt_gate": "gate",
    "router": "cascade",
    "related_docs": true,
    "topic_validation": true,
    "capture": true,
    "clean_nudge": true
  },
  "router": {"band": null, "local_timeout_s": 0.3, "jev_timeout_s": 1.0},
  "capture": {
    "min_turns": 5, "idle_minutes": 45, "cold_minutes": 55, "inbox_cap": 30,
    "daily_soft_cap_usd": 3.0, "max_budget_usd": 1.0, "model": "session"
  },
  "jev": {"key_env": "TYPESAFE_API_KEY", "key_file": "~/.config/typesafe/api_key"},
  "related_hops": 2
}
```

**Which model decides each prompt** (`features.router`):

| mode | how a prompt is classified | data leaving the machine | typical latency |
|---|---|---|---|
| `cascade` (default; `on` is an alias) | local Qwen3-Embedding classifier; Jev only when it is unsure (`router.band`, logit distance from the cut; `null` = the fitted 0.69) | the unsure ~30–40% | ~30 ms local, ~250 ms with Jev |
| `local` | local classifier only | nothing | ~30 ms |
| `jev` | TypeSafe Jev for every prompt; local classifier if Jev fails | every prompt | ~250 ms |
| `off` | keyword matching only | nothing | <10 ms |

The local classifier is fitted on Qwen3-Embedding-0.6B vectors and the Jev combiner on `jev-1.13.0` answers
(`scripts/kb-router-local.json`, `scripts/kb-router.json`); swapping either model needs a refit, so they are
not config keys. Without a TypeSafe key, `cascade` and `jev` fall back to the local classifier.

**TypeSafe key** — never put the key itself in a config file. `jev.key_env` names the environment variable to
read it from (default `TYPESAFE_API_KEY`); otherwise it is read from `jev.key_file`. The `jev` block is honoured
only in the global config and env, never in a repo's `.kb/config.json`, so a repo cannot redirect where the key
is read from.

**Capture fork model** (`capture.model`): `session` (default) runs the fork on the session's own model, which
reuses its prompt cache (~$0.10–0.25 per fork); any other value (e.g. `claude-haiku-5-5`) is passed to
`--model` as-is and pays for the full uncached transcript.

`prompt_gate`: `gate` (read list + enforcement), `hint` (advisory `[KB HINT]` only) or `off`. `clean_nudge`
also accepts the legacy `clean.enabled`. `max_budget_usd` caps one fork; `daily_soft_cap_usd` only warns. A
directory without `index.json` enables nothing.

The KB root is resolved the same way for every hook: `KB_ROOT` env, else the main
checkout of the git common dir (worktrees share one KB), else the cwd. Inspect the
effective values and where each comes from:

```bash
python3 ~/.claude/kb/scripts/kb_config.py show [dir]
```

The repo `.kb/config.json` also holds the `clean` thresholds (read by `kb-clean-due.py`)
and `obsidian` settings (read by `kb-obsidian.py`).

---

## Reference docs

- `SKILL.md` — the routing contract Claude follows.
- `STYLE.md` — how KB docs are written (atomic, declarative, why-not-what).
- `TOPIC_GUIDE.md` — the topic-tag system.
- `workflows/*.md` — the maintenance playbooks.
- `tests/test_self_audit_e2e.py` — end-to-end tests for the self-audit scripts.
