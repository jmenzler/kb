---
name: bootstrap
description: Stand up a starter KB for an existing (brownfield) codebase. Extracts a deterministic AST skeleton (graphify/tree-sitter) — real files, symbols, call/import edges — then writes atomic KB docs on top in STYLE, seeds index.json + topics.json, and runs clean to settle structure. The AST gives the what/where; you supply the why.
args: "<code_root> [--auto]"
---

# Workflow: bootstrap

Create a KB for a codebase that doesn't have one yet. The skeleton comes from a
**deterministic AST pass** (no hallucinated structure); you add the semantic layer.

## Steps

1. **Scaffold.** If no `.claude/knowledge/index.json`, run `init` first (empty
   scaffold + `.kbignore` baseline + inbox).

2. **Extract the AST skeleton** (factual structure, no LLM). Running this *is* the
   graphify check — don't probe `which graphify` first (it installs as a uv tool off the
   default PATH; the script imports it directly from the uv-tool path). Just run it and
   read the exit:
   ```bash
   python3 ~/.claude/kb/scripts/kb-ast.py <code_root> \
       --out .claude/knowledge/.kb/ast-graph.json
   ```
   - **Exit 0 + digest printed** → graphify works. The digest gives **core abstractions**
     (god-nodes: most-connected symbols, with `file:line`), **clusters** (candidate
     folders/topics → member files), and counts. Do **not** load the full graph; `--out`
     keeps it in `.kb/` (gitignored) for spot lookups only. AST cache lands in
     `.kb/ast-cache/`.
   - **Exit 2 ("graphify not installed")** → now you know it's absent. Fall back: explore
     the codebase with Glob/Grep (and parallel explore agents) to find the same structure
     manually.

3. **Harvest existing prose knowledge** — the AST gives *what/where* from code, but the
   *why* (design rationale, domain theory, gotchas, decisions) lives in non-code docs.
   Scan the repo for them:
   - Planning / design dirs: `.planning/`, `docs/`, `design/`, ADRs, RFCs.
   - Knowledge-bearing files anywhere: `*.md` named like RESEARCH, ARCHITECTURE,
     DECISIONS, NOTES, ROADMAP, SPEC, AUDIT; READMEs below the repo root.
   - Skip code, lockfiles, generated/vendored content, and anything in `.kbignore`.
     **Usually skip existing graphify output** (`.planning/graphs/`, `graphify-out/`,
     `GRAPH_REPORT.md`) — it's derived from the same code AST you already extracted, so
     it adds no new *why*. Include it only if it carries hand-authored prose.

   Present the candidate list to the user and **ask which to ingest** (default: the
   obviously knowledge-bearing ones; let them add/drop). For each approved file, **copy
   it — never move — into `.claude/knowledge/inbox/_sources/`** (the source stays put; the
   repo is untouched). Flatten name collisions with a path-derived prefix.

   `inbox/_sources/` is **agent INPUT only** — raw prose the extraction agents read in
   step 5. It is NOT reconciled into the KB directly (that would duplicate what the agents
   distil from it) and is removed before `clean` (step 7). Keep a map of each copy → its
   original repo path; agents cite the **original** in provenance, not the copy.

4. **Plan the docs + assignments** from the digest + harvested knowledge (main thread,
   stays in context):
   - **god-nodes** = the components/abstractions worth a doc each (OMS, dispatcher,
     router…). Highest-degree first.
   - **clusters** = the **unit of agent assignment** (one agent per cluster, or per few
     small clusters). They also suggest a *target* folder/topic layout — but that's a
     planning hint for the `clean` step, NOT something agents create. Agents write flat
     concept-titled `.md` into `inbox/`; `clean` Pass 1 (step 7) builds the folder tree
     when it reconciles. Don't pre-create KB folders.
   - Cross-reference the harvested prose: a concept that recurs there but has no
     god-node (a domain model, an invariant, a "why we chose X") still deserves a doc.
   - Produce a doc plan: per cluster, the doc(s) to write, the AST `file:line` anchors,
     and which harvested source files are relevant. **Confirm with the user** (unless
     `--auto`) before dispatching.

5. **Dispatch extraction agents — parallel, output to `inbox/`.** This is the
   context-heavy part; delegate it so the main thread never reads the whole codebase.
   Use **Sonnet agents** (`Agent` with `model: sonnet`, write-capable e.g.
   `general-purpose`); send independent clusters in one batch per the parallel-agents
   skill. Batch by cluster so each agent's scope is bounded.

   The orchestrator fills the per-assignment fields, then hands the agent the **extraction
   brief** verbatim (the agent has none of this conversation's context). The brief is
   tuned to extract *valuable, durable* knowledge and discard the ephemeral — most of what
   it reads should NOT become a doc:

   ````text
   You are a staff engineer building a knowledge base. Mine your assigned slice of this
   repo for DURABLE, HARD-WON knowledge and write it as atomic KB docs — and throw away
   most of what you read. The bar is high: capture only what a new senior engineer would
   be glad to know and could NOT re-derive in 30 seconds from the code or the git log.

   ASSIGNMENT
   - Components / concepts: {god-nodes for this cluster}
   - Code anchors: {file:line list from the AST digest}
   - Source material to read (staged copies): {inbox/_sources/ file paths}
   - Cite these by their ORIGINAL repo paths (the copies are temporary):
     {map of each staged copy → original repo path}
   - KB writing style: read {abs path to STYLE.md} and match it.

   VALUABLE — capture this:
   - The WHY: why this design, why not the obvious alternative, what constraint forced it.
   - Invariants/contracts not visible in a signature — what must always hold, what breaks
     if it's violated.
   - Non-obvious gotchas that actually bit someone: the bug that cost a day, the sharp
     edge, the footgun, the "do not do X — it silently corrupts Y".
   - Validated conclusions: a benchmark's VERDICT and the trend it revealed; a debug
     session's ROOT CAUSE and the generalizable lesson; an experiment's settled finding.
   - Domain concepts and mental models the code assumes you already understand.

   NOISE — discard this:
   - Anything the code/AST already states: signatures, types, and mechanical control flow.
     Do NOT narrate wiring — "A calls B to get C, then passes it to D" is worthless; the
     AST already has every edge. Capture the IDEA the wiring serves, or write nothing.
   - Blow-by-blow process: debugging steps, "then I tried…", incremental status, task
     checklists, phase-by-phase plans, status percentages, churn.
   - Dead hypotheses and FALSE EUREKAS — an insight later proven wrong is not knowledge.
     Only the correction survives.
   - Trivia reconstructable from one `git log` or one read of the file.
   - Planned/future work written as if it exists. Document only the CURRENT state. Never
     cite a file path or module that isn't on disk yet — a planned path reads as a dead
     reference and fails the doctor. Describe what IS, not what's coming.

   READ BETWEEN THE LINES. The sources won't hand you the concept. A 500-line debug log
   exists to deliver one root-cause principle; a benchmark file's value is a conclusion no
   single row states; a planning doc's value is the decision and its rationale, not the
   task list around it. SYNTHESIZE the underlying idea — do not transcribe. For planning
   material, prefer summaries / research / state / decisions / audits; skip granular phase
   task-plans. For scratchpads and debug logs, keep the final validated root cause and the
   transferable lesson; drop the dead ends — UNLESS a dead end itself teaches "don't try X,
   it fails because Y", which is worth one line.

   SUPERSESSION. When a source contradicts itself over time (early belief → later
   correction), only the corrected understanding survives. If the wrong turn is itself
   instructive, capture it AS the lesson ("we assumed X; it's actually Y because Z") —
   otherwise drop it entirely. Never present a superseded claim as current.

   OUTPUT
   - Write atomic, concept-titled .md files into {abs path to .claude/knowledge/inbox/} —
     one concept per file, prose not code dumps, in the KB style above.
   - Frontmatter: `intent: add` and `sources:` = the ORIGINAL repo paths each claim came
     from (real code paths + original doc paths) — never the `inbox/_sources/` copies,
     which are temporary and get removed.
   - WRITE NOTHING RATHER THAN NOISE. If a source yields no durable knowledge, skip it.
     A few high-signal docs beat exhaustive coverage; empty output is a valid result.
   - Touch ONLY the inbox. Never write to `index.json`, `topics.json`, or any KB folder.
   - Return only the filenames you wrote, each with a one-line reason — or "none" with why.
   ````

   Agents write to `inbox/` only (staging never writes the KB; `clean` reconciles), and
   return just the filename list — keeping the main context clean.

6. **Seed the structural docs** (main thread — these need the global AST view, not a
   single cluster). Write into `inbox/` too: `overview.md` (architecture from cluster map
   + top god-nodes), `data-flow.md` (from `imports`/`calls` edges), `file-paths.md` (from
   the file→symbol map).

7. **Reconcile via `full-clean`.** First **remove `inbox/_sources/`** — it was agent
   INPUT (harvested copies), now consumed; the originals stay in the repo, untouched. The
   inbox then holds only the KB drafts to reconcile: agent-authored component docs
   (step 5) + structural docs (step 6). `full-clean` does the integration the agents
   deliberately skipped:
   - Pass 0 — drain/reconcile the inbox drafts into the KB (ADD/UPDATE/SUPERSEDE, dedup
     overlapping drafts), register entries in `index.json`, seed `topics.json`.
   - Pass 1 — reshape folders/splits/merges on the seeded set.
   - Pass 2/3 — integrity (kb-doctor) + graph/topic optimization verify it. Provenance
     should resolve cleanly because drafts cite original repo paths, not the removed
     `_sources/` copies.
   This is also the single quality gate over agent output — drafts that drift from STYLE
   or duplicate each other get normalized here, not in the main thread.

## Notes

- **Confirm before dispatching** unless `--auto` — review the doc plan + assignments
  (step 4) first. `--auto` also skips the harvest prompt (step 3) and ingests the
  obviously knowledge-bearing files by default.
- **Inbox is the single aggregation point.** Agent drafts and structural docs land in
  `inbox/`; harvested source copies stage in `inbox/_sources/` (agent input only, removed
  before clean). `clean` is the only thing that writes the KB. This is what makes
  delegation safe — parallel agents can't corrupt the KB or race on `index.json`; worst
  case is a messy inbox that `clean` reconciles.
- **Bound the fan-out.** On a large codebase, dispatch agents in waves (a few clusters
  at a time) rather than one giant batch — keeps the inbox reviewable and avoids
  spawning dozens of agents at once.
- Re-runnable: `kb-ast.py` caches per-file, so re-extraction is cheap. Adding docs later
  is just `capture` + `clean`.
