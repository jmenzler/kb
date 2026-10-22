---
name: full-clean
description: Whole-KB re-audit (clean --full). Parallel write-capable subagents read every KB doc + its code + the narrative history and write delta drafts into the inbox (the bootstrap pattern, turned inward); then the shared reconcile/structure/integrity/coverage/finish protocol runs, plus a from-the-docs-up taxonomy redesign. A rare, deliberate re-audit (monthly, or after a big refactor) — accept the LLM cost; completeness is the point and the work is parallel. Reuses clean.md for every shared step. Proposes and applies on confirm.
args: "[--auto] (apply without per-item confirm)"
---

# Workflow: full-clean (`clean --full`)

The deep re-audit. Where incremental `clean` reviews only what changed, `full-clean` re-audits
**every doc** and may **redesign the topic taxonomy wholesale**.

> **Shared protocol lives in `clean.md`.** This file is a thin superset — it adds (1) the
> parallel fan-out engine, (2) large-inbox reconcile delegation, and (3) the taxonomy redesign.
> For every other step (checkpoint, the reconcile single-write-path protocol, structure,
> integrity, coverage/drift, finish) and both cross-cutting principles (division of labor,
> narrative tier), **do exactly what `clean.md` says** — they are origin-agnostic. Don't
> duplicate them here; read them there.

**`--full` is the bootstrap pattern turned inward.** `bootstrap` builds a KB by fanning parallel
agents over a codebase that write atomic docs into the inbox, then reconciles. `full-clean` does
the same — except the agents read the **existing KB doc, its code, and the narrative history
around it**, and write **delta drafts** (corrections, additions, provenance, harvested lessons,
free-form topic proposals) into the inbox instead of whole new docs. The inbox is the work buffer;
reconciliation is the single write path. The orchestrator never loads doc bodies — agents read,
the inbox holds drafts, the drain integrates.

> **Where the rules live (read this once).** The two fan-out stages run through dedicated agents:
> **`kb:clean-reviewer`** (Stage 2) and **`kb:clean-reconciler`** (Stage 3). Each agent's
> *definition* is the contract — the per-doc / per-draft procedure, the atomic-archive loop, the
> draft shape, STYLE, the bounce rules. **You (the orchestrator) never hand-compose those rules
> into a brief, and never substitute a generic agent for them.** That drift — a brief that lost
> the draft-filename prefix, or omitted the atomic-archive rule — is exactly what caused the inbox
> collisions and the 52-draft context-overflow crash on the last real run. You supply only the
> per-run **assignment** (the variable slots each agent declares as its inputs). Your job is
> orchestration: partition, dispatch, the central `index.json`/`topics.json` writes, and the gates.

## The run, in four stages

| Stage | What happens | KB mutated? |
|-------|--------------|-------------|
| **1 · PLAN** | Survey structure, partition into semantic sections, assign agents | no |
| **2 · REVIEW → inbox** | Checkpoint (clean.md Step 2); fan out `kb:clean-reviewer` per section → delta drafts + free-form topics → inbox | no (inbox only) |
| **3 · INTEGRATE → KB** | Reconcile via `kb:clean-reconciler` (clean.md Step 4); structure (clean.md Step 5) | **yes** |
| **4 · VERIFY** | Integrity + coverage (clean.md Steps 6–7); connections + **taxonomy redesign** | fixes only |

Then **Finish** (clean.md, plus the completion gate below). Stage 2 writes only the inbox;
Stage 3 is the only stage that mutates the KB; Stage 4 operates on settled content. **Accept the
LLM cost** — completeness is the point, and the work is parallel.

---

# Stage 1 · PLAN

Before mutating anything, produce and present a plan — the first action of a full clean.

1. **Rough-structure survey.** Read `index.json` (folder/file map + descriptions) and run the
   cheap scans (`kb-doctor`, `kb-graph-full`, `kb-coverage`) for integrity + connectivity +
   provenance-coverage baselines. A structural read, not a body read — the orchestrator stays light.
2. **Partition into semantic sections.** Group docs into coherent review units by *meaning*, not
   line count — a folder, or a tight topic cluster, is one section. A capable subagent handles a
   whole section (a dozen-plus docs); do **not** split on a line budget. Aim for a handful of
   sections that each cohere (e.g. `components/`, `strategy/`, `solana/+database/`, `root arch+ops`).
3. **Assign one section per agent** = a file selection + the code roots that section documents +
   the narrative records that touch it (matching `bugs/`, `hypothesis/`, `implemented-plans/`
   entries by topic/gh-ref, and `.claude/scratchpad/` TL;DRs — see clean.md § Narrative tier).
   Give each section a short unique **section id** (`s1`…`sN`) — the reviewer prefixes its draft
   filenames with it so parallel agents never collide on a draft path. Maximize parallelism (all
   spawned in one message; wave only if the section count is large).
4. **State the agent brief** (Stage 2) and the **script schedule**: scans now; `kb-ast` before
   structure; `kb-doctor` after reconcile + structure; `kb-coverage` + `kb-ast-links` after
   provenance has landed (so they read true state).

Present the plan (section list, agent count, script order), then execute.

---

# Stage 2 · REVIEW → inbox

**Checkpoint & self-heal first — clean.md Step 2.** (A snapshot copy into `.kb/backups/` is a
reasonable extra net on a full run.)

## Fan-out review (the `--full` engine)

Dispatch **one `kb:clean-reviewer` agent per planned section, all in one message** (wave only if
the section count is large). The agent definition is the contract — it specifies the per-doc
review (match-against-code, provenance discovery, narrative harvest), the delta-draft shape, the
triage bar, and the exact report format. **Do not hand-compose a review brief, and do not
substitute a generic agent.** You supply only the **assignment** (the agent declares these as its
inputs):

- **section id** — short, unique (`s1`…`sN`); the agent prefixes every draft filename with it, so
  two agents never write the same inbox path.
- **KB docs to review** — this section's file selection.
- **code roots** the section documents.
- **narrative records** to mine — absolute paths to the matching
  `.claude/knowledge/{bugs,hypothesis,implemented-plans}/` entries + the `.claude/scratchpad/` dir
  (read-only; see clean.md § Narrative tier).
- **inbox** + **inbox/_reports/** paths, the **STYLE.md** path, **today's date**.
- **known doctor / coverage flags** touching this section, to verify.

Each agent owns one section, writes only the inbox, and returns its report filename + a tally. The
inbox is the only write target, so agents cannot race on the KB or `index.json`; the section-id
prefix keeps their draft *files* disjoint even when two drafts legitimately target the same doc.

> **Agent type unavailable?** Its definition file (`~/.claude/agents/kb:clean-reviewer.md`) **is**
> the brief — spawn a `general-purpose` agent and hand it that file's body verbatim plus the
> assignment. One source of truth either way; never paraphrase the contract from memory.

**Coverage guard (don't skip a dead section).** After fan-out, reconcile the returned section
reports against the planned section list. Any planned section with **no report** (agent died /
model unavailable — this happens) → re-dispatch it (single agent) before Stage 3. Never proceed to
Finish with a section unreviewed: the `--mark` step would snapshot it as clean and the next
incremental run would skip it permanently.

---

# Stage 3 · INTEGRATE → KB

## Reconcile — the single write path (clean.md Step 4, delegated)

A `--full` run produces 100+ drafts — too many for the orchestrator to apply directly. Dispatch
**`kb:clean-reconciler` agents in parallel**. The agent definition is the contract: the atomic
per-draft loop (analyze → write → archive one draft fully before the next; **never batch** — the
failure mode is a context-overflow death that loses the idempotency of completed-but-unarchived
edits), the live re-classification (it applies UPDATE/NOOP and **bounces ADD + SUPERSEDE back to
you**), STYLE adherence, and provenance verification all live there. **Do not hand-compose a
reconcile brief and do not substitute a generic agent** — the brief that omitted the atomic-archive
rule is what crashed a 52-draft agent into a manual checkpoint-revert.

Your job is the **partition** (the only per-run variable) and the **central writes**:

- **Partition by disjoint TARGET doc, not by source section.** Two sections' drafts can target the
  same doc; group every draft hitting one doc into ONE agent, so no two agents edit a doc
  concurrently. Cap each partition at **~25–30 drafts** — more overflows an agent's context
  mid-run. Size partitions by **draft count**, not section count.
- **Dispatch all partitions in one message.** Thin assignment per agent: its draft list (or glob),
  its **disjoint target-doc set**, the inbox path, the STYLE.md path, today's date.
- **Apply ADD and SUPERSEDE centrally — yourself.** Agents leave these in the inbox and report
  them; you own every `index.json` / `topics.json` write. ADD = create the doc + register it
  (specific topics, see clean.md Step 4). SUPERSEDE = per-item confirm (**always**, even under
  `--auto`), write the removed block to `.kb/superseded/`, then rewrite as current truth.
- **Reconcile coverage guard.** An agent that stopped early reports its remaining drafts →
  re-dispatch the remainder as a smaller partition. Never proceed with un-archived drafts left in
  the inbox: the next run re-applies them and double-edits a doc.

> **Agent type unavailable?** `~/.claude/agents/kb:clean-reconciler.md` is the brief — paste its
> body into a `general-purpose` agent plus the assignment.

After reconcile, every reviewed doc is confirmed current (`UP-TO-DATE`) or updated, and provenance
is set KB-wide (the full-run guarantee). The `_reports/` files feed the Connections pass and the
summary.

## Structure — clean.md Step 5

Reshape the tree per clean.md Step 5, using the fan-out's `STRUCTURE`/`DUP` report signals as the
primary input (the AST corroborates). A god-node in the AST flags a central component deserving its
own doc; an AST cluster is a candidate folder grouping. Long-file split candidates you choose not
to act on now go to the **deferred log** (see Finish), not into the void.

---

# Stage 4 · VERIFY

**Integrity — clean.md Step 6.** **Coverage + drift — clean.md Step 7** (fully lit now that
provenance is KB-wide; on a legacy pre-provenance KB it no-ops). Drift should be near-empty — the
fan-out just reconciled it; reconcile any residual. Undocumented high-centrality files you choose
not to document now go to the **deferred log** (Finish).

## Connections + taxonomy redesign

Build the graph on the settled, provenance-bearing structure: `kb-graph-full.py`.

**`full-clean` redesigns the taxonomy from the docs up.** This stage is **mandatory** — not
optional, not deferrable. The whole vocabulary and all assignments are rebuilt; the point is not to
trim but to **capture conceptual relationships missed before** (pairs/clusters where a reader of one
would want the other, currently sharing no topic; "0 isolated docs" only means every doc shares
*some* topic, not the *right* ones). Run it as two passes — never tag against the existing fixed
list, which entrenches the old taxonomy:

1. **Free-form proposal** — already collected: each fan-out report carries its docs' unrestricted
   proposed topics (the reviewer's per-doc step).
2. **Consolidation.** One agent (or the orchestrator) reads the entire file→proposed-topics matrix
   and fuzzy-matches across it: cluster near-synonyms into one canonical topic, drop one-off labels
   that link nothing, promote a phrase recurring across several docs into a real topic. The
   consolidated vocabulary — which *emerged* from what the docs are about — becomes the new
   `topics.json`; every doc is then tagged from the consolidated set. This surfaces a cross-cutting
   concern as a repeated free-form phrase even when no existing topic names it.

Then enforce two invariants and propose the before/after topic→doc matrix for confirmation before
writing (it touches `index.json` + `topics.json` only, never doc bodies):
- **Every topic links ≥2 docs.** A singleton connects nobody → merge into a broader topic or drop.
- **No topic blankets a whole large folder.** A folder-wide tag has no routing power → split into
  finer per-file tags.

Then resolve the remaining graph signals (conceptual judgment, driven by what the fan-out *read*):
- **Primary — fan-out `MISSING-LINK` findings** (in the reports): a subagent that read both docs
  judged them related → add a shared topic or cross-ref.
- **Catch-net — AST (filtered):** `kb-ast-links.py` lists doc pairs whose `sources:` import each
  other but share no topic. **Most are noise** (a hub module imported everywhere pairs with every
  doc). For each ask: *would a reader of A want B?* Add only on yes; reject incidental-import hubs.
- **Isolated docs / islands** → connect, merge, or accept. **High-degree hub docs** → review first
  for accuracy; errors there propagate widest.

Style is applied at every write point in **KB style (`STYLE.md`)**, never as a separate pass.

---

# Finish — clean.md

Run **clean.md § Finish** (re-confirm `kb-doctor`, summarize, archive `_reports/`, refresh Obsidian).
Two full-run specifics for the summary + marker:
- The summary reads the `_reports/` (sections reviewed + agent count, `UP-TO-DATE` vs delta counts,
  drafts reconciled, provenance set, taxonomy before/after) **before** they are archived.
- **Update the incremental marker (`kb-changed.py --mark`) only if every planned section was reviewed**
  (Coverage guard). A skipped section must not be marked clean, or the next incremental run skips it
  permanently.

## Completion gate (do not declare done early)

A full clean is complete only when ALL of these hold — check them explicitly before claiming done.
(The prior run declared "complete" with the taxonomy redesign skipped and had to be reopened by the
user; "deferred" was a cop-out. Don't repeat it.)

- [ ] Every planned section has a report (Stage 2 coverage guard).
- [ ] Inbox drained — `inbox/*.md` empty but for `_TEMPLATE.md`; no un-archived drafts remain.
- [ ] All bounced ADD / SUPERSEDE drafts applied centrally.
- [ ] **Taxonomy redesign ran** (Stage 4) — `topics.json` rebuilt from the consolidated free-form
      set, or an explicit stated finding that no change was warranted. Skipping it is not a valid close.
- [ ] `kb-doctor` re-run; every residual flag annotated as intentional in the summary.
- [ ] Coverage + drift run; drift near-empty.
- [ ] Deferred structural work logged (below).
- [ ] Marker updated **only** if every planned section was reviewed.

## Deferred work — log it, don't drop it

Long-file split candidates and undocumented high-centrality files you consciously defer must be
**recorded**, or the next `--full` rediscovers them from scratch and no one learns they are known.
Append them to `.kb/deferred.md` (a machinery file — gitignored, like the review-queue) with the
date and the one-line reason, and surface the list in the summary. The next run reads it to tell
known-deferred from newly-found, so the backlog shrinks instead of resetting every run.

## Commit policy

The pre-clean checkpoint (Stage 2 / clean.md Step 2) is the **only** automatic commit. KB content
changes are left **staged but uncommitted** for the user to review the diff — state this once and
stop; do not repeatedly ask "commit now?". Skill-machinery changes under `~/.claude/skills/` are a
separate concern and are never auto-committed alongside KB content.
