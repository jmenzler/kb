# Scripts

Everything the plugin executes: hook entry points, the libraries they share, and the CLI tools the skills tell
Claude to run. Hooks reference this folder through `${CLAUDE_PLUGIN_ROOT}`; skills and KB indexes reach it
through the stable `~/.claude/kb/scripts/` link that every session start refreshes.

All of it is standard-library Python (plus two shell wrappers), because hooks run on every prompt with the
system interpreter and no virtualenv. The one exception is the router daemon, which `uv` starts in its own
throwaway environment. Configuration lives in `kb_config.py`, which every hook consults before doing anything,
so a new hook should start with an `enabled(...)` check and must exit 0 on any error.
