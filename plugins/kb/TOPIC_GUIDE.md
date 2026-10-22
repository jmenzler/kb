# Knowledge Graph Topic Guide

Documents are connected by shared topic tags from `index.json` files. Deterministic — no embeddings, no ML. Pure tag intersection.

## Topic Registry

`.claude/knowledge/topics.json` — flat JSON array of all allowed topic slugs. **This is the source of truth.** Any topic used in an `index.json` must exist in this registry. A PreToolUse hook (`validate-topics.py`) blocks writes with invalid topics.

## How Topics Work

Two layers, merged at load time:

| Layer | Location | Scope | Style |
|-------|----------|-------|-------|
| **Folder-level** | The folder entry, in its *parent* index (root `index.json` for a top-level folder, the parent folder's `index.json` for a sub-folder) | Applied to ALL files under that folder, at any depth | Broad, categorical (`architecture`, `hedging`, `dex-integration`) |
| **File-level** | Folder `index.json` file entry | Specific to one file | Precise, technical (`gate-stack`, `clmm`, `avellaneda-stoikov`) |

A doc's final topic set = **file topics ∪ the topics of every folder containing it**.
Folders may nest arbitrarily deep, and inheritance composes the whole chain: a doc at
`findings/recovery/hazard-curve.md` carries its own tags plus `findings/`'s plus
`findings/recovery/`'s. Outer folder tags should get broader the further out you go —
if a sub-folder's tag is no broader than its files', it belongs on the files.

## Graph Mechanics

After every `Read` of a KB `.md` file, a PostToolUse hook injects related files into context:

```
[KB graph] Potentially relevant files (resolve with: resolve-file.py <name>):
  lifecycle(arbitrage,hedging) -> spread-capture: basis-stats-observer, ...
  oms(order-execution) -> architecture: event-dispatcher, portfolio, ...
```

Format: `direct_file(shared_tags) -> topic: hop1, hop2 | topic: hop3`

- **Direct**: files sharing topic tags with the one you just read
- **1-hop**: files sharing tags with a directly-related file (friends-of-friends)
- Same-folder results are excluded (already visible from the folder's `index.json`)
- Filenames are stems (no `.md`). Ambiguous names get a folder-initial prefix (`f/overview`, `s/overview`)
- Topic tags in parentheses show WHY the connection exists

## Topic Granularity (connections must be real)

A topic exists to assert a **semantic link**: two docs that share it should be ones where
a reader who cares about one would genuinely want the other. The graph is only as useful
as that promise — if sharing a tag *doesn't* mean "read both," the tag is manufacturing
noise, not signal. Assign topics by the connection they make, never by coverage or a
count.

- **The link test.** Before giving doc B a topic that doc A already carries, ask: *would
  someone reading A — because of this exact concept — want B?* Yes → real edge, tag it.
  "Not necessarily, they just both touch this area" → the topic is too coarse; it names a
  region, not a shared idea.
- **Topics name concepts, not areas.** A precise mechanism / decision / invariant
  (`cosine-inversion`, `eb-shrinkage`, `seed-before-reset`) makes a sharp link — anyone
  who shares it shares the actual idea. A subsystem or layer (`evaluation`,
  `architecture`, a component name) is a *category*: many docs touch it without being
  about the same thing, so co-membership is incidental. Categories belong at the **folder
  level** — folders group without pretending to be edges (same-folder pairs are excluded
  from routing anyway).
- **Let concepts define topics.** Don't invent an umbrella tag to "connect" docs that
  aren't actually connected, and don't pad a doc to a topic count. A doc with three precise
  tags routes better than one with eight vague ones.
- **Size follows from meaning and adapts to the codebase.** A genuinely central concept in
  a large, complex system legitimately spans many docs — that's a real hub, not a mistake,
  and bigger codebases have bigger hubs. There's no target number. The graph measures a
  tag's breadth *relative to the whole KB* and only down-ranks it once it's broad enough
  that co-membership stops implying relatedness (`hub_threshold` in `kb_graph.py`, which
  scales with KB size). You aim for real links; the mechanism handles scale.

Two anti-patterns break the link test in ways that look reasonable while tagging:

- **Never repeat a containing folder's tag at file level.** A folder tag is inherited by every
  doc under it, at any depth, so restating it adds no routing — it just names the doc's region twice
  and manufactures file-level edges between docs whose only real relation is living in the
  same directory. `kb-doctor` flags these ("File topics repeating their folder's tag").
- **Tag what the doc asserts, not its backdrop.** What a doc *runs on*, is *measured with*,
  or merely *mentions* is not what it is about: a version-renumbering table tagged with the
  protocol thresholds it happens to cite, or a language-choice decision tagged with the
  simulator it targets, both pass "does it touch this?" — a test this guide never sanctions.

`clean` Pass 3 still flags tags that have grown into noise so they can be split or demoted
to the folder level — but the cheapest fix is making the link real when you tag it.

## Resolving Filenames

```bash
python3 ~/.claude/kb/scripts/resolve-file.py lifecycle       # → hedging/lifecycle.md
python3 ~/.claude/kb/scripts/resolve-file.py f/overview     # → future-optimizations/overview.md
python3 ~/.claude/kb/scripts/resolve-file.py overview       # → all 4 matches
```

Handles stems (no `.md`), full names, and disambiguated prefixes.

## Adding a New Topic

1. Add the slug to `.claude/knowledge/topics.json` FIRST (keep alphabetical order)
2. Then use it in any `index.json` file

The PostToolUse validator blocks any write that uses an unregistered topic. If you get blocked: either pick a close match from the existing list, or add your new topic to the registry first.

## Adding a File to the Graph

1. Create the `.md` file in the appropriate KB folder
2. Add entry to the folder's `index.json`:
```json
"new-file.md": {
  "description": "What this file covers",
  "topics": ["topic-from-registry", "another-topic"]
}
```
3. If it's a root-level file, add to root `index.json` instead
4. Assign **specific** topics — each one a real shared concept (the *link test* in
   **Topic Granularity** above). Broad categories belong at the folder level, precise
   concepts at the file level. No target count; tag the connections that are real.

## Removing a Topic

1. Remove it from all `index.json` files that reference it
2. Remove it from `topics.json`
3. Run `check()` to verify no orphaned docs: `python3 -c "from kb_graph import check; print(check())"`
