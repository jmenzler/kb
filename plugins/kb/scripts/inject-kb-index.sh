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
This project has a knowledge base: its curated, authoritative account of how the system works — architecture, rationale, decisions, measured results, status. The index below shows what it covers *and what it does not*.

When a task touches a covered topic, invoke the `kb:base` skill and read the connected docs before answering or acting; check claims about current behaviour against the code. When the index doesn't cover it, say so and go to the code. For structure questions (what calls X, how A and B connect) use `kb-query` via the `code_graph` source. Maintenance: `/kb:clean`; staging a finding: `/kb:capture`.

PREAMBLE
python3 "$CONVERTER" "$KB_INDEX"
echo "</kb-available>"

# Arm a KB-clean ask if one is due (delivered by kb-clean-stop.py; switch: features.clean_nudge).
python3 "$HERE/kb-clean-due.py" 2>/dev/null || true
