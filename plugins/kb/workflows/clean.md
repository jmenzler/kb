---
name: clean
description: Incremental KB maintenance — audit and curate the docs changed since the last clean, then reconcile the contribution inbox. Keeps the KB factual, complete, concise, well-connected, current. Owns the shared protocol (checkpoint, reconcile, structure, integrity, coverage, finish) that full-clean reuses. Proposes and applies on confirm. For a whole-KB re-audit + taxonomy redesign, use `--full` (see full-clean.md).
args: "[--auto] (apply without per-item confirm)"
---

# Workflow: clean (incremental maintenance)

> **`--full` → read `full-clean.md` instead.** That is the deep re-audit superset: parallel
> fan-out over *every* doc + a from-the-docs-up taxonomy redesign. This file is the
> incremental/maintenance run **and the canonical home of the shared protocol** (checkpoint,
> reconcile, structure, integrity, coverage, finish) that full-clean references — so full-clean
> stays a thin superset and there is one source of truth for the steps both share.

Audit and curate the KB, then reconcile the contribution inbox. Scope is **what changed since
the last clean** — small enough for the orchestrator to review directly, no fan-out. Modeled
on the "lint" pass common to LLM-wiki systems.

**Default: propose, then apply on confirm.** Every structural or judgment change is shown as a
plan and confirmed before applying. Flag `--auto` applies the whole plan without per-item
confirmation (riskier — LLM corruption of canonical docs is the main failure mode; use only
when you trust the diff). **SUPERSEDE is always per-item confirmed, even under `--auto`.**

---

## Two cross-cutting principles (shared)

### Division of labor — who owns what

`clean` mixes deterministic checks with semantic judgment. Route each kind of work to the
right owner; never script a judgment, never hand-judge a mechanical check.

| Work | Nature | Owner |
|------|--------|-------|
| Integrity (dead refs, index↔disk, index.json schema, graph metrics) | deterministic | **script** (`kb-doctor`, `kb-graph-full`) |
| Drift / staleness (does the doc still match the code) | semantic | **LLM** — reads doc + code |
| Provenance *discovery* (which src files a doc derives from) | comprehension | **LLM** — reads code |
| Content correction (fix drift, supersede, add missing) | judgment | **LLM** — written as inbox delta drafts |
| Provenance *writing* (verify path exists → set frontmatter) | mechanical | **script** — inside the reconcile step |
| Connections / topic links (should A link B) | conceptual judgment | **LLM** |
| AST-implied links | mechanical catch-net | **script → LLM filters** (`kb-ast-links`) |
| Narrative "why" — durable lesson from history | comprehension → distilled | **LLM** — harvests narrative tier into prose |

The recurring mistake is treating a **script's output as the answer** for the comprehension
rows. `kb-ast-links` emits *import edges*, not conceptual links — most are incidental
(everything imports `asset_registry`/`orders`/`pool_cache`). It is a net to catch a link the
LLM missed, never a to-do list to apply wholesale.

### Narrative tier — the *why* behind the *what*

The KB proper is current-state-only ("is" state). But the repo also accumulates **narrative**
records — how things came to be, what was tried and rejected, why a design exists. These are
not KB docs (they're history, not current truth), yet they hold the most durable knowledge.
When reviewing a doc, mine the narrative for its topic and distil a durable lesson into KB
prose — a `REFUTED` hypothesis's "don't do X, it fails because Y", a plan's decision rationale,
a bug's root-cause gotcha becomes a gotcha/invariant in the relevant doc. Do **not** ingest
verbatim and do **not** add a provenance axis for narrative; the raw record stays grep-able as
the deep archive. (full-clean mines this at scale via the fan-out; an incremental run harvests
it only for the changed docs it reviews.)

Harvest sources (two classes — **mind the paths**, scratchpad escapes the KB root):

| Class | Path | KB scripts scan it? | Harvest signal | Disposition |
|-------|------|---------------------|----------------|-------------|
| KB-resident | `.claude/knowledge/{bugs,hypothesis,implemented-plans}/` | no (`.kbignore`) | `VERIFIED`/`REFUTED`/`PARTIAL` verdict, plan + `.progress.md`, root cause | read in place, stays |
| External | `.claude/scratchpad/` *(one level ABOVE the KB root)* | no (outside root) | the `**TL;DR:**` line per `## Session` block | **read-only input — never write or copy into the KB** |

Scratchpad is outside `.claude/knowledge/`, so KB scripts never touch it — but it is pure input
you may only read, never write.

---

## Step 1 — Scope (what changed)

```bash
python3 ~/.claude/kb/scripts/kb-changed.py    # → changed *.md, or "FULL"
```
Scope = changed docs ∪ docs named in `kb-doctor`/`kb-graph-full` findings ∪ docs touched by
inbox reconciliation ∪ `.kb/review-queue.md`. `kb-doctor` and `kb-graph-full` are cheap
whole-KB scans (a subprocess walks every doc, returns compact findings — the orchestrator never
loads the KB to find problems); act on every finding they return. If `kb-changed` reports
`FULL` (never cleaned), this is too big for an incremental run — switch to `full-clean.md`.

## Step 2 — Checkpoint & self-heal (shared)

0. **Checkpoint first (recovery net).** `clean` mutates canonical docs in place; git is the only
   undo. Run `git status --porcelain .claude/knowledge/`. If the KB dir is dirty, commit a
   checkpoint (`git add .claude/knowledge && git commit -m "kb: pre-clean checkpoint"`) or, if
   the user declines, warn that corruption won't be cleanly reversible and get explicit
   confirmation. Not a git repo → warn the same.
1. **Self-heal staging dirs.** Ensure `inbox/`, `inbox/processed/`, `inbox/_reports/` exist and
   `inbox/_TEMPLATE.md` is present (see `init.md`); ensure `.kbignore` carries the baseline
   (`knowledge-graph`, `graphify-out`, `inbox`, `.kb`) so staging + tool dirs never leak into
   the graph/doctor. `inbox/_reports/` is **review output, not KB content** — the `_` prefix
   marks it non-reconcilable.

## Step 3 — Review the changed set (incremental)

The changed set is small — the orchestrator reviews it **directly** (no fan-out). For each
changed doc: read it + the code it documents (its `sources:`, or locate the implementing files),
judge whether every claim still holds, verify provenance (`sources:` correct + `updated:` date),
and harvest the narrative tier for its topic. Stage any correction / missing provenance /
harvested lesson as an inbox delta draft — same draft shape the inbox uses:

> Frontmatter: `intent: add | update | correct` (advisory — Reconcile re-classifies against the
> live KB), `target: <existing KB doc>` (omit for `add`), `sources:` = ORIGINAL repo paths the
> claim derives from, `captured: <date>`. Body = the corrected fact stated in full, standalone —
> the smallest self-contained claim, KB style (`STYLE.md`), **not** a diff and **not** the whole
> doc. One concept per file.

Copied live values count as drift even when they still match: a count, threshold, default, limit or
list that a code/config file owns (`STYLE.md` § Point to live values) is rewritten as a pointer to that
file/key plus what it means. Dated measurements and historical decisions stay.

Triage bar: a doc correctly labeled *deferred*/*historical*/*research* is not drift, and a
generated/gitignored config (rendered from a `.template`) or a deliberately-planned-but-unbuilt
file is intentional, not a dead ref. Write nothing rather than noise.

## Step 4 — Reconcile the inbox into the KB (shared · the single write path)

Both external contributions and the deltas staged above flow through here. Reconciliation, not
appending: the KB is authoritative and current-state-only; new knowledge updates and supersedes,
stale content is rewritten or deleted, never left beside the new.

**Scale check first.** Count `inbox/*.md` (excluding `_TEMPLATE.md`). A handful → reconcile inline
below; the orchestrator IS the reconciler. **Above ~25 drafts, do NOT reconcile inline** — the
orchestrator's own context overflows mid-run exactly as a subagent's would, and though atomic
archiving (below) makes a re-run recoverable, the dead session is disruptive. Instead delegate to
one or more **`kb:clean-reconciler`** agents per full-clean.md Stage 3 (partition by disjoint target
doc, ~25–30 per agent, apply ADD/SUPERSEDE centrally yourself). If the changed set *and* the inbox
are both large, this isn't an incremental run — switch to `--full`. The atomic per-draft protocol
below is identical whether you apply it inline or an agent does.

Process `inbox/*.md` (exclude `_TEMPLATE.md`; skip `_reports/` and `_sources/`). Treat each
draft as an **atomic unit of work — analyze → write → archive — and complete it fully before
touching the next draft.** Never batch (do not read N drafts, then edit N docs, then archive N):
an in-progress reconcile that dies (context overflow, crash) must leave durable, re-runnable
state, and the only thing that records "this draft is done" is its move to `processed/`. A draft
whose KB write landed but was never archived will be re-applied on the next pass — re-applying a
prose correction double-edits. So archive each draft the instant its write succeeds, in the same
loop iteration. For each draft (two-step — analyze before writing):

- **Analyze.** Read the draft + its `intent`/`target`/`captured`/`sources` frontmatter. An old
  `captured:` means its "truth" may itself be stale — verify against live code before trusting it
  for a SUPERSEDE. Honor the explicit `target`; otherwise locate the KB doc(s) it concerns
  (`<kb-index>` → `kb_graph` related → `Grep`). Re-confirm the classification against the live KB:
  - **NOOP** — already true in the KB. Skip.
  - **ADD** — genuinely new concept; no doc covers it.
  - **UPDATE (extend)** — augments/corrects an existing doc; new + old can both be true.
  - **SUPERSEDE** — directly contradicts/obsoletes existing content (cannot coexist).

  When unsure between UPDATE and SUPERSEDE, treat as UPDATE — never delete on a guess. The draft's
  `intent` is a **hint only** — the live-KB re-classification is authoritative. A `correct` is
  UPDATE unless the claims cannot coexist (then SUPERSEDE). `captured:` is inbox-only: on write set
  the KB doc's `updated:`, never carry `captured:` across.
- **Write** (in **KB style — `STYLE.md`**):
  - UPDATE → edit the target; merge the fact, keep it tight. **Set/refresh `sources:`** (verify
    each path exists — the mechanical guard; drop any that don't and note it) + `updated:`.
  - **SUPERSEDE (destructive — extra care):** quote both old and replacement in the plan; write the
    removed block to `.kb/superseded/<doc-stem>-<date>-<HHMMSS>.md`; then rewrite as current truth
    and delete the stale text. Refresh `sources:` + `updated:`.
  - **Every write that touches an index entry rewrites its description as a ROUTING LINE** — the
    question the doc answers, one line, no numbers, no verdicts (`STYLE.md` § Index descriptions).
    A doc whose content changed usually has a description that drifted toward summarising the new
    finding; fix it in the same edit, or the index slowly becomes a stale second copy of the KB.
  - ADD → create an atomic, concept-titled doc; pick best-fit folder; register in `index.json` with
    **specific topics chosen by the link they make** — a shared topic must mean two docs are
    genuinely related (a reader of one wants the other), not just same-area. Add genuinely-new
    topics to `topics.json` first. See `TOPIC_GUIDE.md` § Topic Granularity. Set `sources:` + `updated:`.
- **Archive** the draft to `inbox/processed/` **immediately after its KB write succeeds**, as the
  closing step of this draft's iteration (don't delete; `mv`) — *then* move to the next draft. The
  inbox is the source of truth: an archived draft is skipped on re-run, an un-archived one is
  re-applied. Batching archives to the end forfeits this.
- **Confirmation:** `--auto` auto-applies NOOP/ADD/UPDATE after showing the plan. **SUPERSEDE is
  ALWAYS confirmed per-item, even under `--auto`** — deleting curated content on an AI-judged
  contradiction is the highest-risk operation; never one-shot it.

After reconcile, every reviewed doc is either confirmed current or updated, and provenance
frontmatter is set on every doc that **received a delta**. (Whole-KB provenance is a full-clean
guarantee; an incremental run touches only the changed set.)

## Step 5 — Structure (shared · reshape the tree)

Settle the file/folder layout **after** content lands but **before** integrity reads it. Drive it
by the conceptual relationship between docs; the AST only corroborates:
```bash
python3 ~/.claude/kb/scripts/kb-ast.py <code_root> --out .claude/knowledge/.kb/ast-graph.json
```
- **Split-vs-keep** — `kb-query.py --ast explain "<symbol>"`: tightly interconnected symbols = one
  cohesive concept, **keep whole**; loosely-coupled sub-clusters = separable → split.
- **Merge** — `kb-query.py --ast path "<docA symbol>" "<docB symbol>"`: a short, dependency-laden
  path = coupling → merge signal.

**The AST is a supplementary signal, not the map.** The KB's heart is the conceptual relationships
between docs, most of which (theory → strategy, rationale, invariants, cross-cutting concerns) have
**no code edge**. Never let "the code isn't coupled" override a real conceptual relationship.

Propose the reorg, then apply on confirm: **group** docs into a folder when several share one
canonical topic and none groups them (categories *emerge* from density; don't pre-plan empty
taxonomies); **split** docs `kb-doctor` flags as long (>400 lines) only when they hold separable
concepts — one cohesive concept stays whole, don't over-fragment; very long (>800) with many
standalone sections → promote to a folder; **consolidate** thin docs only useful jointly (absorbed
file → redirect stub or removed if unreferenced); **move** misfiled docs. All in KB style. A long
doc you consciously choose NOT to split now → log it to `.kb/deferred.md` (date + reason) so it
isn't silently re-surfaced from scratch every run.

## Step 6 — Integrity (shared · from kb-doctor)

Run `kb-doctor.py` **after** content + structure + provenance settle. Resolve each bucket:
- **Auto-apply** (mechanical/safe): *stale code refs* with a single candidate → rewrite; *topics
  registered but unused* → prune from `topics.json`.
- **Confirm each:** *stale refs `AMBIGUOUS`* → show candidates, context picks; *dead code refs*
  (file gone) → remove or repoint — a path cited only to say a file was *deleted/replaced* is
  historical narrative, drop it (git holds history), keep the current-state fact; *index → missing
  file* → fix the entry; *broken provenance* → verify and update/remove; *orphaned docs* →
  tag/delete/leave; *dangling folder/supplementary refs* → fix the ref or create the index.
- Note: a generated/gitignored config (`prometheus.yml` from `.template`) and a deliberately-unbuilt
  planned file (`kill_switch.py "to be created"`) both trip the dead-ref check but are intentional —
  confirm, annotate, leave.

## Step 7 — Self-audit (shared · coverage + drift)

```bash
python3 ~/.claude/kb/scripts/kb-coverage.py
```
- **Drift (REVIEW).** Each flagged doc names the symbol delta its `sources:` files gained/dropped
  since `updated:`. Read, verify, reconcile (Step 4 discipline), refresh `updated:`.
- **Coverage (SUGGESTIONS).** Undocumented central files are ranked doc-gap candidates; centrality
  ≠ doc-worthy, so **you judge**. Genuinely doc-worthy hubs → stage an `add` draft and reconcile;
  **never auto-create**. A hub you judge not-yet-worth-documenting → log it to `.kb/deferred.md`
  (date + reason) rather than re-evaluating it cold next run.
- **Drain the review queue.** If `.kb/review-queue.md` exists, resolve its entries, clear it.

## Step 8 — Connections / topic maintenance (incremental)

Build the graph: `kb-graph-full.py`. Its edges, degrees and hub topics come from **file-level**
topics; folder-level tags are inherited by a whole folder, so they are reported as *folder
groups* (membership) rather than links, and a doc with no file-level topics shows up as
isolated. On an incremental run you **maintain** the topic system, you do not redesign it: fix a broken tag, add a topic for genuinely-new content, retag a doc that
drifted, connect an isolated doc. Supply the conceptual judgment yourself over the changed docs you
read — *would a reader of A want B?* The AST catch-net (`kb-ast-links`) is mostly noise (a hub
module imported everywhere pairs with every doc); use it only to catch a link you missed, never as
a to-do list. **Wholesale taxonomy redesign is a `--full` action — see full-clean.md.**

Style is applied at every write point (Steps 4–8) in **KB style (`STYLE.md`)**, never as a separate pass.

---

# Finish (shared)

1. Re-run `kb-doctor.py` to confirm clean (remaining flags should all be intentional — annotate
   them in the summary).
1b. **Routing check — the index is the product, so test it like one.** Structural integrity says
   nothing about whether a reader lands in the right folder. Spot-check the descriptions of every
   folder touched this run against `STYLE.md` § Index descriptions: does each state the *question*
   rather than the answer, and does every folder description carry at least one `NOT x` naming
   **what** is excluded (never a folder path — paths rot when a folder is renamed)? After a
   taxonomy change (new folder, moved docs, a split), go further and run a **blind probe**: give a
   fresh subagent 8–10 real questions plus the KB root, require it to commit to a folder from the
   root index alone before descending, and have it write results to a file (a wrong first guess is
   the finding; its final message may never arrive). Two failure classes, both actionable: wrong
   folder = the description's exclusion is missing or vague; right folder but wrong answer = the
   doc it landed in is stale or a sibling doc holds the real answer with no pointer between them.
2. **Summarize**: docs reviewed, drafts reconciled (ADD/UPDATE/SUPERSEDE), provenance set, what was
   left for the user.
3. Archive/clear `inbox/_reports/` if present.
4. **Update the incremental marker** so the next run only reviews new changes:
   ```bash
   python3 ~/.claude/kb/scripts/kb-changed.py --mark
   ```
   The marker is per-doc content hashes — it catches docs whose *own* text changed, not cross-doc
   drift, so **run `full-clean` periodically** to re-audit the whole KB.
5. **Refresh the Obsidian vault if enabled** (`.kb/config.json` `obsidian.enabled`, or a vault dir
   already at `obsidian.path`):
   ```bash
   python3 ~/.claude/kb/scripts/kb-obsidian.py
   ```
6. **Commit policy.** The pre-clean checkpoint (Step 2) is the only automatic commit. KB content
   changes are left **staged but uncommitted** for the user to review the diff — state this once and
   stop; do not repeatedly ask "commit now?".
---

At SessionStart, `kb-clean-due.py` (cheap, fail-silent) checks whether an **incremental** clean is
due — inbox drafts pending, `incremental_threshold` docs edited, `review-queue` code-drift impacts,
or never cleaned — and, past the cooldown, arms `.kb/pending-clean-ask.json`. The Stop hook
`kb-clean-stop.py` delivers it once per session, after the first reply, as a `<kb-clean-due>` block
telling the assistant to **ask the user** whether to run `clean` (never auto-runs). `full-clean` is
**never** auto-suggested — a full re-audit is a deliberate user action. Thresholds and cooldown live
in `.kb/config.json` (`clean` block); `clean.mode` and `clean.agent_model` only change the wording of
the ask (which run mode and agent model it suggests). This workflow does not read them: its own
switch is `--auto`. `features.clean_nudge: false` (or legacy `clean.enabled: false`) turns the ask off.
