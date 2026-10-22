---
name: clean
description: Incremental KB maintenance — audit and curate the docs changed since the last clean, then reconcile the contribution inbox. Keeps the KB factual, complete, concise, well-connected, current. Owns the shared protocol (checkpoint, reconcile, structure, integrity, coverage, finish) that full-clean reuses. Proposes and applies on confirm. For a whole-KB re-audit + taxonomy redesign, use `--full` (see full-clean.md).
args: "[--auto] [--full]"
---

# kb:clean

Read `~/.claude/kb/workflows/clean.md` and follow it. With `--full` (whole-KB
re-audit + taxonomy redesign) read `workflows/full-clean.md` in the same folder instead. Shared rules: `STYLE.md`
and `TOPIC_GUIDE.md` at the plugin root; agents `kb:clean-reviewer` and `kb:clean-reconciler` ship with this plugin.

Layout rules for anything you write (index.json shape, nesting, `sources:` frontmatter): `workflows/format.md`.

## Maintenance scripts
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

**`.kbignore`** lists what the graph/doctor/related-hook ignore (gitignore-style). **`.kb/`** holds local
machinery (caches, markers, backups), gitignored.
