# kb — a knowledge base Claude Code actually uses

Claude Code forgets everything between sessions, and a `docs/` folder only helps if Claude thinks to read it.
**kb** gives each repository a curated knowledge base in `.claude/knowledge/` and makes it part of every
session: prompts that touch project knowledge make Claude read the relevant docs first, related docs surface as
it reads, and findings worked out during a session — root causes, measured results, decisions and their reasons —
are captured back into the knowledge base automatically.

## Install

```bash
claude plugin marketplace add <this-repo-url>
claude plugin install kb@kb-marketplace
```

Start a new session, then once:

```bash
python3 ~/.claude/kb/scripts/install.py
```

This sets the one environment variable plugins cannot set, removes old hook copies if you used kb before it was a
plugin, and reports missing tools. Requires Python ≥ 3.9 and `git`; everything else is optional:

| optional | enables | without it |
|---|---|---|
| `uv` | local prompt classifier (downloads Qwen3-Embedding-0.6B, ~1.2 GB, on first use) | keyword matching |
| TypeSafe key in `$TYPESAFE_API_KEY` or `~/.config/typesafe/api_key` | Jev for prompts the local classifier is unsure about | local classifier decides alone |

**Create a knowledge base** in a repository by asking Claude to "init a KB here" (or "bootstrap a KB from this
codebase" for an existing project). It writes `.claude/knowledge/` with an `index.json`, topic folders and an inbox.

## How it works

### A knowledge base per repository

`.claude/knowledge/index.json` maps topics to folders of short markdown docs. Each doc carries topic tags and
`sources:` frontmatter pointing at the code or files it describes. The index can also declare other sources
(code search, SQL, RAG, MCP tools) with when to use each. At session start the index is injected into context,
so Claude can route without reading files.

### The routing gate

Every prompt is classified: does answering it need project knowledge?

1. A local classifier (Qwen3-Embedding + logistic regression, kept warm by a small daemon) decides confident
   cases in ~30 ms.
2. Prompts it is unsure about (~30–40%) go to TypeSafe's Jev (~250 ms).
3. If neither is available, keyword matching against the index decides.

On held-out real messages this routes 90% of KB-relevant prompts to the KB and skips 84–86% of the rest. A routed prompt gets a
read list, other tools are blocked until Claude has invoked the `kb:base` skill, and a reply that skipped the
reading is sent back once. `??` anywhere in a prompt forces the gate.

### Related docs

After Claude reads a KB doc, it is shown up to four docs from other folders that share its topics and that it
has not seen yet this session, so knowledge split across docs gets read together.

### Keeping the knowledge base current

- **Inbox** — new knowledge lands as drafts in `.claude/knowledge/inbox/`; nothing writes straight into the KB.
- **`/kb:clean`** — reconciles the inbox into the docs (adds, updates or supersedes; the KB stays current-state
  only), checks links and provenance, and flags docs whose source code has moved. It is suggested automatically
  when enough has changed.
- **`/kb:capture`** — stage a finding on request ("capture this").
- **Automatic capture** — at session end, after 45 idle minutes or before compaction, a background fork of the
  session (same model, so it reuses the prompt cache: ~$0.10–0.25) reviews the conversation and stages drafts
  for *earned* knowledge only: root causes, measured results, decisions with reasons, refuted assumptions — not
  lookups, generic knowledge or task progress. It is sandboxed to reading and writing inbox drafts. Your next
  prompt gets a one-line note of what it captured.

### Configuration

Every feature can be switched off or tuned globally (`~/.claude/kb-config.json`), per repository
(`.claude/knowledge/.kb/config.json`) or by environment variable (`KB_HOOKS=off` disables everything):

```json
{
  "features": {"prompt_gate": "gate", "router": "cascade", "related_docs": true, "capture": true},
  "capture": {"min_turns": 5, "idle_minutes": 45, "model": "session", "daily_soft_cap_usd": 3.0}
}
```

`router` picks who classifies prompts: `cascade` (local, Jev when unsure), `local` (nothing leaves the
machine), `jev` (Jev for every prompt) or `off` (keywords). `python3 ~/.claude/kb/scripts/kb_config.py show`
prints the effective settings and where each comes from.

### Privacy

- With `router: cascade` or `jev`, the prompt, the end of Claude's previous reply and a summary of the KB index
  are sent to TypeSafe for the prompts Jev classifies. `router: local` keeps everything on your machine.
- Automatic capture runs on your own Claude account, like the session itself.
- The TypeSafe key is read from an environment variable or a key file, never from a config file in a repository.

Full reference — every hook, script, workflow and setting: [`plugins/kb/README.md`](plugins/kb/README.md).

## Development

```bash
ln -s "$PWD/plugins/kb" ~/.claude/skills/kb     # load the working copy in place (kb@skills-dir)
uv run --no-project --with pytest python -m pytest -q tests
```

## License

MIT
