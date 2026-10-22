#!/usr/bin/env bash
# Refresh the KB AST graph — run by the post-commit hook. No-op unless this repo has a
# KB and the just-made commit touched code. Runs in the background so it never blocks
# the commit; extraction is cached/incremental so it's cheap.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -f "$ROOT/.claude/knowledge/index.json" ] || exit 0   # no KB → skip
command -v python3 >/dev/null 2>&1 || exit 0

KB="$ROOT/.claude/knowledge"
SKILLS="$HOME/.claude/kb/scripts"
REV=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null) || exit 0

# Obsidian vault enabled? .kb/config.json obsidian.enabled, OR a legacy vault dir present
# at the configured path (presence = opt-in, back-compat). kb-obsidian.py reads its own path.
VAULT_ENABLED=$(python3 - "$KB" "$ROOT" <<'PY' 2>/dev/null || echo 0
import json, os, sys
kb, root = sys.argv[1], sys.argv[2]
try:
    o = json.load(open(f"{kb}/.kb/config.json")).get("obsidian", {}) or {}
except Exception:
    o = {}
on = bool(o.get("enabled")) or os.path.isdir(os.path.join(root, o.get("path", "kb-vault")))
print(1 if on else 0)
PY
)

CODE_RE='\.(py|ts|tsx|js|jsx|rs|go|java|rb|c|cc|cpp|h|hpp|cs|kt|scala|php|swift|lua|zig|ex|exs|m|jl|dart|sql|sh)$'
if git -C "$ROOT" diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null | grep -qE "$CODE_RE"; then
  CODE=1
else
  CODE=0
fi

# Nothing to do: no code change AND no Obsidian vault to refresh.
[ "$CODE" -eq 0 ] && [ "$VAULT_ENABLED" != "1" ] && exit 0

# Build the background job. On a code commit: rebuild the AST graph, then map this
# commit's impacted docs into the review queue (fresh graph). The Obsidian vault is
# regenerated when enabled (config or legacy presence) — after the AST step so it picks
# up fresh code links. graphify-missing exits cleanly inside kb-ast.py; review-queue
# no-ops without a graph.
CMD=""
if [ "$CODE" -eq 1 ]; then
  CMD="python3 '$SKILLS/kb-ast.py' '$ROOT' --out '$KB/.kb/ast-graph.json' >/dev/null 2>&1; \
    python3 '$SKILLS/kb-review-queue.py' '$KB' --commit '$REV' >/dev/null 2>&1"
fi
if [ "$VAULT_ENABLED" = "1" ]; then
  [ -n "$CMD" ] && CMD="$CMD; "
  CMD="${CMD}python3 '$SKILLS/kb-obsidian.py' '$KB' >/dev/null 2>&1"
fi

# Background — don't block the commit.
nohup bash -c "$CMD" >/dev/null 2>&1 &
