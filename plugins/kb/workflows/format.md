# KB format: index.json, nesting, provenance

How a knowledge base is laid out on disk. Read this before creating or changing docs or indexes (init, bootstrap, clean, capture reconcile). Writing style is in `../STYLE.md`, the topic system in `../TOPIC_GUIDE.md`.

## index.json

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
