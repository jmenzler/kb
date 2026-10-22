#!/bin/bash
# Inject KB index into session context if this repo has one.

HERE="$(cd "$(dirname "$0")" && pwd -P)"
# Stable path to this plugin wherever it is installed (marketplace cache or dev symlink); docs and KB indexes use it.
mkdir -p "$HOME/.claude" && ln -sfn "$(dirname "$HERE")" "$HOME/.claude/kb"
CONVERTER="$HERE/kb_index_to_xml.py"
KB_CONFIG="$HERE/kb_config.py"

# Main checkout's KB (worktrees share it); silent when none or when features.index_inject is off.
KB=$(python3 "$KB_CONFIG" root --feature index_inject 2>/dev/null) || exit 0
KB_INDEX="$KB/index.json"

echo "<kb-available>"
cat <<'PREAMBLE'
This project has a knowledge base — its AUTHORITATIVE source of truth, pre-indexed and fast. Consult it FIRST for ANY question about how this system works — architecture, components, design rationale, theory, invariants, status, "how/why does X work", or how things relate — BEFORE Grep, code-search, semantic-search, auto-memory, or training-data recall. The KB is the default first move, not a fallback; don't skip it because a question "looks simple" or you "already know" — verify against it.

MANDATORY PAUSE: whenever anything in the chat (a task, file, name, project, concept, decision) is mentioned in or associated with anything in the KB, STOP before answering or acting, invoke the `kb:base` skill, and read the ENTIRE connected tree: the matching doc(s), then every relevant doc the `[KB graph]` hook surfaces, then theirs, recursively, plus `kb-query explain "<topic>" --docs` per seed topic. Continue only when a pass surfaces no unread relevant doc. Relevance prunes branches; convenience ("already know it", "small edit") never does. Re-triggers every turn a new KB-associated topic appears.

Two ways to use it, both rendered in `<kb-index>` below:
  • READ a doc — match the question to an `<entry>` and Read it for the how/why prose. Reading a doc auto-surfaces related docs via the topic graph.
  • TRAVERSE with `kb-query` — for structure/relationship questions (what calls or imports X, how A and B connect, a symbol's or doc's neighborhood) use the `code_graph` source (`explain`/`neighbors`/`path`/`query` over the code + topic graphs) INSTEAD of grepping; deterministic, cites file:line.

Invoke the `/kb:base` skill for routing help or KB maintenance (clean/capture/init/sources). The KB index is pre-loaded below so you can route without re-reading `index.json`:
PREAMBLE
python3 "$CONVERTER" "$KB_INDEX"
echo "</kb-available>"

# Arm a KB-clean ask if one is due (delivered by kb-clean-stop.py; switch: features.clean_nudge).
python3 "$HERE/kb-clean-due.py" 2>/dev/null || true
