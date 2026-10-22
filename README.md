<div align="center">

# kb

**A knowledge base Claude Code actually uses.**

[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757)](#getting-started)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB)](#requirements)
[![Dependencies: stdlib](https://img.shields.io/badge/dependencies-stdlib_only-success)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

[Overview](#overview) · [Features](#features) · [Getting started](#getting-started) · [How it works](#how-it-works) · [Configuration](#configuration) · [Privacy](#privacy)

</div>

## Overview

Claude Code forgets everything between sessions, and a `docs/` folder only helps if Claude thinks to open it.
**kb** gives each repository a curated knowledge base in `.claude/knowledge/` and wires it into every session:
prompts that touch project knowledge make Claude read the relevant docs before answering, related docs surface
as it reads, and what a session works out — root causes, measured results, decisions and their reasons — flows
back into the knowledge base on its own.

```text
 your prompt ──▶ router ──▶ needs the KB? ──yes──▶ read the matching docs ──▶ answer
                                │                         │
                                no                  related docs surface
                                ▼
                             answer          session ends ──▶ background capture ──▶ inbox ──▶ /kb:clean ──▶ KB
```

## Features

- **Routing gate** — every prompt is classified in ~30 ms by a local model, with TypeSafe Jev for unsure cases;
  KB-relevant prompts must read the matching docs first.
- **Related docs** — reading a doc surfaces up to four unread docs from other folders that share its topics.
- **Coverage awareness** — the index also shows what is *not* documented: Claude says so, goes straight to the
  code, and the finding becomes capture material instead of a guess.
- **Automatic capture** — a cached background fork of the session stages earned knowledge into the inbox at
  session end, after idle time or before compaction.
- **Curated, not appended** — `/kb:clean` reconciles the inbox into current-state docs and flags docs whose
  source code has moved.
- **Graph queries** — ask what calls X or how A and B connect across the code graph and the topic graph.
- **Switchable** — every feature can be turned off or tuned globally, per repository or per environment variable.

## Getting started

### Requirements

- [Claude Code](https://docs.claude.com/en/docs/claude-code)
- Python ≥ 3.9 and `git` (all scripts are standard-library only)
- Optional: [`uv`](https://docs.astral.sh/uv/) for the local prompt classifier, and a
  [TypeSafe](https://typesafe.ai) API key for Jev

### Install

```sh
claude plugin marketplace add jmenzler/kb
claude plugin install kb@kb-marketplace
```

Start a new session, then run the setup check once:

```sh
python3 ~/.claude/kb/scripts/install.py
```

It sets the one environment variable a plugin cannot set, removes hook copies left from pre-plugin versions, and
lists anything missing.

> [!NOTE]
> The first prompt in a repository with a knowledge base starts the local classifier, which downloads
> Qwen3-Embedding-0.6B (~1.2 GB) once. Until it is ready, prompts are routed by Jev or by keyword matching.

### Create a knowledge base

Open Claude Code in your repository and ask:

```text
init a KB here
```

For an existing codebase, `bootstrap a KB from this codebase` drafts docs from the code structure first. Both
write `.claude/knowledge/` with an `index.json`, topic folders and an inbox.

### Commands

| Command | What it does |
|---|---|
| `/kb:base` | Route a question to the KB, run graph queries, or start init / bootstrap / sources workflows |
| `/kb:capture` | Stage a finding in the inbox ("capture this") |
| `/kb:clean` | Reconcile the inbox and audit changed docs; `--full` re-audits the whole KB |

> [!TIP]
> Put `??` anywhere in a prompt to force the gate when the router lets something through.

## How it works

### A knowledge base per repository

`.claude/knowledge/index.json` maps topics to folders of short markdown docs. Each doc carries topic tags and
`sources:` frontmatter that points at the code or files it describes, which is how `/kb:clean` notices drift.
The index can also declare other sources (code search, SQL, RAG, MCP tools) and when to use each. The index is
injected at session start, so Claude can route without reading files. Worktrees share the main checkout's KB.

### Routing

1. A local classifier (Qwen3-Embedding + logistic regression, kept warm by a small daemon) decides confident
   prompts in ~30 ms.
2. Prompts it is unsure about (~30–40%) go to Jev (~250 ms).
3. If neither is available, keyword matching against the index decides.

On held-out real messages this sends 90% of KB-relevant prompts to the KB and skips 84–86% of the rest. A routed
prompt gets a read list; other tools are blocked until Claude invokes `kb:base`, and a reply that skipped the
reading is sent back once.

### Automatic capture

Once a session has five or more turns, a fork of it — same model, so it reuses the session's prompt cache
(~$0.10–0.25 per fork) — reviews the conversation at session end, after 45 idle minutes, or before compaction.
It keeps only *earned* knowledge (root causes, measured results, decisions with reasons, refuted assumptions),
skips lookups, generic knowledge and task progress, deduplicates against the KB and inbox, and writes one small
draft per claim. The fork is sandboxed to reading and writing inbox drafts. Your next prompt gets a one-line note
of what it captured.

## Configuration

Settings layer as environment > repository (`.claude/knowledge/.kb/config.json`) > global
(`~/.claude/kb-config.json`) > defaults. Every key is optional:

```json
{
  "features": {
    "prompt_gate": "gate",
    "router": "cascade",
    "related_docs": true,
    "capture": true
  },
  "capture": { "min_turns": 5, "idle_minutes": 45, "model": "session", "daily_soft_cap_usd": 3.0 },
  "jev": { "key_env": "TYPESAFE_API_KEY", "key_file": "~/.config/typesafe/api_key" }
}
```

| `features.router` | Who classifies prompts | Leaves your machine |
|---|---|---|
| `cascade` (default) | local model; Jev when it is unsure | the unsure ~30–40% |
| `local` | local model only | nothing |
| `jev` | Jev for every prompt | every prompt |
| `off` | keyword matching | nothing |

`KB_HOOKS=off` disables everything for a shell. Inspect the effective settings and where each comes from:

```sh
python3 ~/.claude/kb/scripts/kb_config.py show
```

The full reference — every hook, script, workflow and setting — is in [`plugins/kb/README.md`](plugins/kb/README.md).

## Privacy

With `router: cascade` or `jev`, the prompt, the end of Claude's previous reply and a summary of the KB index are
sent to TypeSafe for the prompts Jev classifies. `router: local` keeps routing entirely on your machine.

Everything sent to Jev is scrubbed first (`scripts/kb_redact.py`): provider API keys, bearer tokens, JWTs,
private keys, credentials in URLs, `password=`/`token:`-style values, long random strings, email addresses, and
the exact values of any environment variable named like a key, token, secret or password. A prompt that itself
contains a secret is never sent: the local classifier decides it. The local router log is masked the same way.
Automatic capture runs on your own Claude account, like the session it forks.

> [!IMPORTANT]
> Never put the TypeSafe key in a config file. `jev.key_env` names the environment variable to read it from;
> otherwise it is read from `jev.key_file`. Both are honoured only in the global config, so a repository cannot
> redirect where the key is read from.

## Development

```sh
ln -s "$PWD/plugins/kb" ~/.claude/skills/kb    # load the working copy in place (kb@skills-dir)
uv run --no-project --with pytest python -m pytest -q tests
```
