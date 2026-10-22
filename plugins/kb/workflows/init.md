---
name: init
description: Bootstrap the KB system into a repo with no KB — scaffold index.json, topics.json, inbox + template, gitignore, check the global hooks (install.py --check). Content comes later via capture + clean.
---

# Workflow: init

Bootstrap the KB system into a repo that doesn't have one. Scaffolds the structure;
content comes later via `capture` (stage to inbox) + `clean` (reconcile into KB).

## Steps

1. **Guard.** If `.claude/knowledge/index.json` already exists → stop. Suggest `clean`
   (to curate) or `capture` (to stage content) instead. Do not overwrite.

2. **Scaffold** under `.claude/knowledge/`:
   - `index.json` — root index. Infer `description` from the repo's README / package
     manifest (package.json, pyproject.toml, Cargo.toml, go.mod). Start with empty
     `entries`; **for a code-backed KB seed the two built-in universal sources**
     (`code_graph` → `kb-query.py`, `backstory` → `transc why`) so graph + session-
     background routing works from day one (omit for a prose-only KB — `code_graph`'s topic
     half still works; advertise once there's an AST graph). Project-specific sources
     (`sql`, `rag`, …) come later via `sources`:
     ```json
     {
       "description": "<one-line purpose of THIS project's KB>",
       "entries": {},
       "sources": {
         "code_graph": {
           "tool": "python3 ~/.claude/kb/scripts/kb-query.py",
           "use_for": "Structure across BOTH graphs joined by provenance — what calls/imports X (code), which docs relate to X (topics), the path between two components/docs, a symbol's or doc's neighborhood. Cites file:line + doc paths.",
           "info": "Subcommands: query \"<q>\" [--dfs] | path \"A\" \"B\" | explain \"X\" | neighbors \"X\". Searches code (AST) + topic docs by default; --ast or --docs to scope one layer. Code nodes annotate «doc: …» (documenting KB doc via sources:); doc results show shared-topic neighbors + documented symbols. Graph at .kb/ast-graph.json (post-commit refresh); topic graph from index.json."
         },
         "backstory": {
           "tool": "transc why <file>[:line]",
           "use_for": "The Claude session that wrote a line/doc — its reasoning and the decisions around it. Use when the WHY is missing, or before changing a surprising design.",
           "info": "Feed a doc's `sources:` path: `transc why <file>[:line]` blames → replays the originating session's conversation (`transc explain <hash>` if you already have the commit). Claude-authored commits replay the session; human/older commits show only the commit summary."
         }
       },
       "supplementary_docs": {}
     }
     ```
   - `topics.json` — empty registry: `[]`
   - `.kbignore` — the **single source of truth** for exclusions (gitignore-style: dir
     names, paths, globs; one per line). There are no hardcoded defaults, so the
     baseline must be listed here. Write it exactly like this:
     ```
     # KB exclusions — ignored by the graph, doctor, and related-files hook.
     # gitignore-style: a dir name matches anywhere; paths/globs match KB-relative paths.
     # Baseline (keep these):
     knowledge-graph
     graphify-out
     inbox
     .kb
     # Add project-specific exclusions below, e.g.:
     # implemented-plans
     # hypothesis
     # bugs
     # drafts
     # *.wip.md
     ```
   - `inbox/`, `inbox/processed/`, and `inbox/_reports/` directories (`_reports/` holds
     `clean`'s fan-out review reports — `_`-prefixed = non-reconcilable, never KB content)
   - `inbox/_TEMPLATE.md` — the contributor template (verbatim):
     ```markdown
     ---
     intent: add        # add | update | correct
     captured: YYYY-MM-DD   # date staged — clean uses this to flag stale input
     target:            # existing doc path if known, else leave blank
     sources: []        # repo-relative paths this knowledge comes from
     ---
     # <concept or claim — what this is about>

     <The knowledge itself. State what is true. If correcting/updating, say what is
     now wrong or has changed. Be concrete. Prose, not code dumps.>
     ```
   - `.kb/config.json` — local KB settings (`.kb` is gitignored), layered over the global
     `~/.claude/kb-config.json` and built-in defaults (see README "Configuration"; check the
     result with `python3 ~/.claude/kb/scripts/kb_config.py show`).
     **Walk the user through setup** — explain each knob, take their answer, fall back to the
     default. Don't dump all at once: ask the ones marked **ask**, state the rest with
     defaults and that they're tunable later in this file.

     | Key | What it controls | Default | Ask? |
     |-----|------------------|---------|------|
     | `features.router` | How messages are routed to the KB. `on` = local model, with the uncertain ~30% sent to TypeSafe Jev: the message, the last ~1,200 chars of the previous reply and a KB summary (index descriptions + doc names) go to `api.typesafe.ai`. `local` = never leaves the machine. `off` = keyword matching only | `on` | **ask** (say what is sent) |
     | `features.capture` | Automatic capture: background forks review the session at session end, after idle and before compaction, and write drafts into `inbox/`. Each fork costs money (capped at `capture.max_budget_usd`, typically well under it) and its drafts trigger clean nudges | `true` | **ask** (cost + inbox drafts) |
     | `features.prompt_gate` | Read gate on KB-related messages: `gate` (enforced), `hint` (advisory only), `off` | `hint` | default; mention |
     | `features.index_inject`, `related_docs`, `topic_validation` | `<kb-index>` at session start; related docs after a KB Read; topic checks on index writes | `true` | default |
     | `features.clean_nudge` | Whether a due incremental clean is raised with the user after the first reply | `true` | **ask** (on/off) |
     | `related_hops` | After a KB Read, how many hops of related docs to surface — `1` = directly-related only, `2` = also friends-of-friends (richer but more tokens/Read) | `2` | **ask** |
     | `clean.mode` | Which run mode the clean ask suggests once the user approves — `review` (drafts only), `safe` (non-destructive + stage SUPERSEDE), `auto` (auto-confirmable changes). Wording of the ask only | `auto` | default; mention |
     | `clean.agent_model` | Model the clean ask suggests for an optional background clean agent. Wording only | `sonnet` | default; mention |
     | `clean.incremental_threshold` | Edited-doc count that flags a clean (`0` = disable this trigger) | `5` | default; tunable |
     | `clean.review_queue_threshold` | Commit-flagged code-drift-doc count that flags a clean (`0` = disable) | `1` | default; tunable |
     | `clean.suggest_cooldown_hours` | Don't re-ask within this window | `24` | default; tunable |
     | `capture.*` | `min_turns` 5, `idle_minutes` 45, `cold_minutes` 55, `inbox_cap` 30, `daily_soft_cap_usd` 3.0 (warning only), `max_budget_usd` 1.0 (per fork) | — | default; tunable |
     | `obsidian.enabled` | Generate + keep an Obsidian vault view of the KB (post-commit hook refreshes it) | `false` | **ask** (on/off) |
     | `obsidian.path` | Where the vault lives, repo-relative (gitignore it) | `kb-vault` | ask only if enabling |

     `full-clean` is **never** auto-suggested regardless of these — a full re-audit is a
     deliberate user action. The Obsidian vault is best *after* there's content; if the user
     enables it on an empty KB, the hook just regenerates it once docs land (or they run
     `kb-obsidian.py`, which also flips `obsidian.enabled` true). Seed the file with their
     answers + defaults (omit `capture` unless they changed a threshold):
     ```json
     {
       "_note": "Local KB settings (.kb is gitignored), layered over ~/.claude/kb-config.json (kb_config.py show). features: per-repo switches for the hooks. related_hops: 1 = direct related docs only after a KB Read; 2 = also friends-of-friends. clean: clean-due thresholds + wording of the ask (kb-clean-due.py). obsidian: vault view (kb-obsidian.py).",
       "features": {
         "index_inject": true,
         "prompt_gate": "hint",
         "router": "on",
         "related_docs": true,
         "topic_validation": true,
         "capture": true,
         "clean_nudge": true
       },
       "related_hops": 2,
       "clean": {
         "incremental_threshold": 5,
         "review_queue_threshold": 1,
         "suggest_cooldown_hours": 24,
         "mode": "auto",
         "agent_model": "sonnet"
       },
       "obsidian": {
         "enabled": false,
         "path": "kb-vault"
       }
     }
     ```
     If the user picks a non-default `obsidian.path`, gitignore **that** path in step 3
     instead of `kb-vault/`.

3. **Gitignore the inbox** (staging only; the reconciled KB is what's committed). Add
   to the repo's `.gitignore`:
   ```gitignore
   .claude/knowledge/inbox/
   .claude/knowledge/.kb/
   kb-vault/
   ```
   `inbox/` is local staging (`_TEMPLATE.md` recreated by init / clean self-heal).
   `.kb/` holds all KB machinery — AST cache (`.kb/ast-cache/`), the AST graph
   (`.kb/ast-graph.json`, which can be **several MB** on a large codebase), the
   incremental marker (`.kb/last-clean`), and SUPERSEDE recovery backups
   (`.kb/superseded/`) — all local/derived, never committed. Both are created on demand
   by the scripts. `kb-vault/` (repo root, not under `.claude/`) is the optional Obsidian
   export (step 6) — also local/derived; the rule is harmless if the vault is never created.

   **Write these `.gitignore` rules and commit them BEFORE generating `.kb/ast-graph.json`
   or running `bootstrap`** — otherwise the large graph can get staged. Then **verify**
   nothing under `.kb/` is tracked: `git status --porcelain .claude/knowledge/.kb` should
   be empty; if a `.kb/` file is already staged, `git rm -r --cached .claude/knowledge/.kb`.
   Some pre-commit frameworks stash/restore the worktree and can silently drop an
   *unstaged* `.gitignore` edit — so stage and commit the `.gitignore` change itself, don't
   leave it dangling.

4. **Verify the KB hooks.** All hooks are global (canonical list: `scripts/hooks.json`) and
   decide per repo through `kb_config.py`, so there is no per-repo wiring. Check them and
   the tools they need:
   ```bash
   python3 ~/.claude/kb/scripts/install.py --check
   ```
   If it reports anything missing, run `python3 ~/.claude/kb/scripts/install.py`
   (merges the hooks into `~/.claude/settings.json` with a backup; idempotent) and install
   any missing required tool (`uv`, `claude`, `git`). Optional pieces it lists (`graphify`,
   `transc`, the TypeSafe key, `/usr/share/dict/words`) only degrade the matching feature.

5. **AST refresh hook (code-backed KBs only).** Install the per-repo git post-commit
   hook that keeps `.kb/ast-graph.json` current after commits touching code (cached,
   incremental, background — never blocks the commit; no-op on docs-only commits):
   ```bash
   bash ~/.claude/kb/scripts/install-ast-hook.sh
   ```
   Skip for prose/research KBs with no code. Requires graphify for the actual
   extraction (`uv tool install graphifyy`); the hook self-skips if it's absent.

6. **Offer** (ask, don't impose):
   - Add a "Knowledge Source Precedence" stanza to the repo's `CLAUDE.md` instructing
     KB-first consultation for technical questions.
   - Declare data sources now → hand off to the `sources` workflow.
   - Populate the KB now → `bootstrap` (existing codebase) or `capture` + `clean`.
   - **Obsidian vault** — if they enabled `obsidian` in step 2 *and* the KB already has
     content, generate it now: `python3 ~/.claude/kb/scripts/kb-obsidian.py`
     (reads `obsidian.path`, sets `obsidian.enabled` true). Empty KB → skip; the post-commit
     hook generates it once docs land. (The ask happens in step 2's config setup.)

7. Confirm the scaffold, then stop. Validate `index.json` and `topics.json` parse.
