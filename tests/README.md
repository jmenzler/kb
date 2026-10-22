# Tests

Behaviour tests for the plugin's scripts, kept outside `plugins/kb/` so they are not installed with it. Most run
the hook scripts as subprocesses against throwaway KBs in `tmp_path`, with `HOME` redirected, because the
hooks' contract is their stdin/stdout JSON and their side effects in `~/.claude/kb-gate/`. Network and model
calls (Jev, the local classifier, `claude -p` forks) are replaced with stubs; nothing here needs a key.

Run with `uv run --no-project --with pytest python -m pytest -q tests`.
