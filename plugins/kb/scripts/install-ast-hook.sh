#!/usr/bin/env bash
# Idempotently install (or refresh) the KB AST post-commit hook into a repo.
# Worktree- and hooksPath-safe. Coexists with other post-commit hook content.
# Usage: install-ast-hook.sh [repo_root]
set -euo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel)}"
HOOK=$(git -C "$ROOT" rev-parse --git-path hooks/post-commit)
START="# kb-ast-hook-start"
END="# kb-ast-hook-end"
BLOCK="$START
bash \"\$HOME/.claude/kb/scripts/kb-ast-refresh.sh\"
$END"

mkdir -p "$(dirname "$HOOK")"
if [ -f "$HOOK" ]; then
  sed -i.bak "/$START/,/$END/d" "$HOOK" && rm -f "$HOOK.bak"   # strip prior block
else
  printf '#!/usr/bin/env bash\n' > "$HOOK"
fi
printf '%s\n' "$BLOCK" >> "$HOOK"
chmod +x "$HOOK"
echo "installed kb-ast post-commit hook → $HOOK"
