# KB Writing Style

KB docs are **read by an LLM** to answer questions and route to code. Optimize for
machine extraction and retrieval, not human narrative. `clean` writes to this style
when reconciling the inbox and rewrites existing docs that violate it.

## The unit: an atomic, declarative doc

- **One concept per doc.** Title it by what it asserts ("Order lifecycle: PENDING →
  APPROVED → routed"), not a vague label ("Orders"). If a doc covers multiple
  independently-citable concepts → split.
- **Concise but complete.** Every sentence carries a fact. No filler, no
  throat-clearing ("This document describes…"), no restating the heading. If deleting
  a sentence loses no information, delete it. Atomic ≠ thin: include all the facts
  that belong to this one concept.
- **Bounded.** Over ~400 lines → split into sub-topics (clean enforces).

## Voice and tense

- **Declarative, present tense, current state.** State what *is* true: "The risk gate
  rejects orders exceeding `max_position`." Not "we added", "recently changed", "used
  to". The KB reflects the system as it is now — git holds history.
- **Active voice.** "The dispatcher fans out events" not "events are fanned out".
- **No hedging.** Reads are authoritative. Write only what is verified true. If
  something is unknown, don't speculate — omit it, or record it as a gap in
  `status-gaps.md`. Never "probably", "might", "I think".

## Structure for scanning

- **Lead with the answer (inverted pyramid).** First line/section = the most important
  fact. An LLM may read only the top of the doc.
- **Tables for any 2-axis data** — mappings, comparisons, field lists, status. LLMs
  parse tables cleanly; prefer them over prose paragraphs for structured facts.
- **Short sections with headings.** Each section self-contained — makes sense without
  reading top-to-bottom.
- **Lists for enumerable facts**, prose for reasoning/rationale.

## Content — what to include

- **Why and the non-obvious**, not just what. Code already says *what*; the KB adds
  rationale, invariants ("must always be true"), constraints, gotchas, design
  intent, and cross-component relationships.
- **Exact identifiers as anchors.** Name real things: `ClassName`, `function()`,
  `src/path/file.py`, event names, config keys. These let the reader jump to code.
- **Conceptual, not code dumps.** Describe behavior and contracts. Include a code
  snippet ONLY when the exact signature/shape/format *is* the knowledge — never paste
  whole functions. Point to the file instead.
- **Provenance.** Set `sources:` frontmatter to the files/commit the doc derives from.

## Index descriptions are routing lines, not summaries

A doc's prose states the answer; its **index description states the question**. The two
have opposite jobs, and writing the description like a mini-abstract breaks routing in two
ways: a reader answers from the index without opening the doc (and reports a stale or
partial claim as truth), and every number in the description becomes a second copy that
must track the doc.

| Don't (summary) | Do (routing line) |
|-----------------|-------------------|
| "Gray zone closes at TWO boundaries: β*=0.14503 fresh vs 0.265 permanent…" | "Where the availability boundary sits for each blocking schedule, and why they differ" |
| "RQ11 v1: certificates mounted on recovery hold on the sim tier, arms 1-4 green…" | "Whether certificates can be mounted on recovery, and on which tier that was shown" |

Rules for a **file** entry: name the question, one line, no numbers, no verdicts
(`PASS`/`REFUTED`/`CONFIRMED`), no conclusions.

A **folder** entry states the kind of question it answers, then what it **excludes** — the
exclusion half is load-bearing, because it is what collapses two plausible folders into one.
Every folder description carries at least one `NOT x`.

- Name **what** is excluded, never **where** it lives: "NOT what we measured", not
  "NOT measurements (findings/)". A path couples every folder to every other folder's name
  and rots the moment one is renamed; the whole index is in context, so the reader matches
  on vocabulary.
- Keep the excluded thing in the vocabulary its owning folder uses, so the match is
  findable: "NOT what we measured" works because that folder calls itself measured truths.
- Prefer stable categories to instance lists — a description enumerating today's docs goes
  stale each time one lands.

**Root-level entries ship in every session** (the session-start hook renders only the root
index), so keep them to about a line. Entries inside a folder index are paid only when that
folder is opened and can afford a little more — but they still name the question, not the
answer.

## Consistency

- **One term per concept.** Don't alternate synonyms ("pool" vs "venue" vs "market"
  for the same thing) — pick one; consistent terms aid retrieval and dedup.
- **Match existing KB vocabulary and topic tags** (`topics.json`).

## Anti-patterns (clean rewrites these)

| Smell | Fix |
|-------|-----|
| Narrative / changelog ("recently we…", "as of #123") | State current truth; drop the history |
| Buried lede (key fact in paragraph 4) | Move it to the top |
| Wall of prose for structured data | Convert to a table |
| Pasted code blocks | Replace with conceptual description + file path |
| Hedging / speculation | Delete or move to `status-gaps.md` |
| Duplicated content across docs | Consolidate; one canonical home |
| Vague identifiers ("the handler") | Name the exact symbol/file |
| Restating the heading in the first sentence | Delete the restatement |
