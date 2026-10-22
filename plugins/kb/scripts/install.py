#!/usr/bin/env python3
"""Prepare ~/.claude/settings.json for the `kb` plugin and check what its features need.

  python3 install.py            remove legacy KB hook registrations (the plugin's hooks/hooks.json replaces them),
                                set required env, then --check
  python3 install.py --check    report plugin state, leftover duplicates, env and tools; exit 1 if something
                                required is missing
Install the plugin first (README "Install"): from its git marketplace, or for development by linking
<repo>/plugins/kb to ~/.claude/skills/kb (loads in place as kb@skills-dir).
Per-repo behaviour is switched in `.claude/knowledge/.kb/config.json` (see kb_config.py).
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
PLUGIN_LINK = Path.home() / ".claude" / "skills" / "kb"
CLAUDE_FALLBACK = Path.home() / ".local" / "bin" / "claude"
# Plugins cannot set env; manual capture needs forks, Bash needs ~/.local/bin.
ENV = {"CLAUDE_CODE_FORK_SUBAGENT": "1"}
LEGACY_MARKERS = ("skills/knowledge-base/scripts/", ".claude/hooks/inject-kb-index.sh")
REQUIRED_TOOLS = {"uv": "router daemon (local model)", "claude": "capture forks", "git": "KB root resolution"}
OPTIONAL = {"graphify": "code graph for kb-query / bootstrap", "transc": "backstory source"}
# Hooks run without the interactive shell's PATH additions and aliases, so look where these usually live.
KNOWN_LOCATIONS = {
    "graphify": [Path.home() / ".local" / "bin" / "graphify"],
    "transc": [Path.home() / ".claude" / "scripts" / "transc"],
}


def _legacy(command: str) -> bool:
    return any(m in command for m in LEGACY_MARKERS)


def install(settings_file: Path) -> list[str]:
    """Strip legacy KB hooks and set env; returns the changes made (empty when nothing changed)."""
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    changes = []
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if not _legacy(h.get("command", ""))]
            changes += [f"removed legacy {event} hook: {h['command']}" for h in g.get("hooks", []) if h not in kept]
            g["hooks"] = kept
        hooks[event] = [g for g in hooks[event] if g.get("hooks")]
        if not hooks[event]:
            del hooks[event]
    env = settings.setdefault("env", {})
    for key, value in ENV.items():
        if env.get(key) != value:
            env[key] = value
            changes.append(f"set env {key}={value}")
    if changes:
        if settings_file.exists():
            shutil.copyfile(settings_file, settings_file.with_name(
                f"{settings_file.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}"))
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    return changes


def check(settings_file: Path) -> tuple[str, bool]:
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    lines, ok = [], True
    installed = (PLUGIN_LINK / ".claude-plugin" / "plugin.json").exists() or any(
        k.startswith("kb@") and v for k, v in settings.get("enabledPlugins", {}).items())
    if not installed:
        lines.append("plugin kb is not installed (README: Install)")
        ok = False
    elif settings.get("enabledPlugins", {}).get("kb@skills-dir") is False:
        lines.append("plugin kb@skills-dir is disabled in user settings (claude plugin enable kb@skills-dir)")
        ok = False
    legacy = [h.get("command", "") for groups in settings.get("hooks", {}).values() for g in groups
              for h in g.get("hooks", []) if _legacy(h.get("command", ""))]
    for command in legacy:
        lines.append(f"legacy hook still registered (runs twice with the plugin): {command}")
        ok = False
    for key, value in ENV.items():
        if settings.get("env", {}).get(key) != value:
            lines.append(f"missing env {key}={value}")
            ok = False
    for tool, why in REQUIRED_TOOLS.items():
        if not shutil.which(tool) and not (tool == "claude" and CLAUDE_FALLBACK.exists()):
            lines.append(f"missing tool: {tool} — {why}")
            ok = False
    for tool, why in OPTIONAL.items():
        if not shutil.which(tool) and not any(p.exists() for p in KNOWN_LOCATIONS.get(tool, [])):
            lines.append(f"optional, missing: {tool} — {why}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kb_config
    if not kb_config.jev_key():
        jev = kb_config.DEFAULTS["jev"]
        lines.append(f"optional, missing: TypeSafe key (${jev['key_env']} or {jev['key_file']}) — router runs local-only")
    if not Path("/usr/share/dict/words").exists():
        lines.append("optional, missing: /usr/share/dict/words — keyword fallback loses its jargon signal")
    return ("\n".join(lines) or "plugin enabled, no legacy hooks, all tools present"), ok


def main() -> int:
    if "--check" not in sys.argv:
        for change in install(SETTINGS) or ["settings already up to date"]:
            print(change)
    report, ok = check(SETTINGS)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
