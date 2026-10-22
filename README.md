# kb — project knowledge bases for Claude Code

A Claude Code plugin that gives each repository a `.claude/knowledge/` knowledge base and keeps Claude using it:

- **Routing gate** — every prompt is classified (local embedding model, with an optional TypeSafe Jev call for
  uncertain messages); KB-relevant prompts must read the matching docs before answering.
- **Related docs** — reading a KB doc surfaces its unread neighbours on the topic graph.
- **Maintenance** — `/kb:clean` reconciles the inbox and audits the KB; `/kb:capture` stages a finding.
- **Automatic capture** — a cached background fork of the session stages earned knowledge (root causes,
  measured results, decisions) into the inbox at session end, after idle time or before compaction.
- **Switches** — every feature can be turned off globally, per repo or by environment variable.

## Install

```bash
claude plugin marketplace add <this-repo-url>
claude plugin install kb@kb-marketplace
python3 ~/.claude/kb/scripts/install.py      # once: sets env, checks tools (~/.claude/kb appears after the first session)
```

Then run `/kb:base` in a repository, or follow `plugins/kb/workflows/init.md` to create a knowledge base.
Full documentation: [`plugins/kb/README.md`](plugins/kb/README.md).

## Development

```bash
ln -s "$PWD/plugins/kb" ~/.claude/skills/kb     # load the working copy in place (kb@skills-dir)
uv run --no-project --with pytest python -m pytest -q tests
```

Requires Python ≥ 3.9 (standard library only). Optional: `uv` (local router model), a TypeSafe API key at
`~/.config/typesafe/api_key` (Jev for uncertain prompts; without it routing stays on the machine).

## License

MIT
