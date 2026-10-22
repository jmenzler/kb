#!/usr/bin/env python3
"""One KB-root resolver and one switchboard for every automatic KB feature.

Layers, highest wins: env > repo `.claude/knowledge/.kb/config.json` > global `~/.claude/kb-config.json` > defaults.
  env   KB_HOOKS=off (everything off) · KB_ROUTER=on|local|off · KB_CAPTURE_FORK (set inside capture forks: all off)
Features: index_inject · prompt_gate (gate|hint|off) · router (on|local|off) · related_docs · topic_validation ·
capture · clean_nudge (legacy `clean.enabled` maps onto it). A directory without `index.json` enables nothing.

  python3 kb_config.py show [dir]                 effective config with the source of every value
  python3 kb_config.py root [--feature NAME]      print the KB root; exit 1 if none or the feature is off
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

GLOBAL_CONFIG = Path.home() / ".claude" / "kb-config.json"
DEFAULTS = {
    "features": {"index_inject": True, "prompt_gate": "gate", "router": "on", "related_docs": True,
                 "topic_validation": True, "capture": True, "clean_nudge": True},
    "capture": {"min_turns": 5, "idle_minutes": 45, "cold_minutes": 55, "inbox_cap": 30,
                "daily_soft_cap_usd": 3.0, "max_budget_usd": 1.0},
    "related_hops": 2,
}
OFF = {"prompt_gate": "off", "router": "off"}


def kb_root(cwd: Path | None = None) -> Path:
    """The KB folder for a directory: KB_ROOT env, else the main checkout's (worktrees share it), else cwd's."""
    env = os.getenv("KB_ROOT")
    if env:
        return Path(env)
    cwd = Path(cwd or Path.cwd())
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                                capture_output=True, text=True, check=True).stdout.strip()
        kb = Path(common).parent / ".claude" / "knowledge"
        if kb.exists():
            return kb
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        pass
    return cwd / ".claude" / "knowledge"


def launch_cwd(transcript: str | None) -> Path | None:
    """Directory the session started in: the first `cwd` recorded in its transcript (the shell cwd drifts)."""
    if not transcript or not Path(transcript).exists():
        return None
    with open(transcript, errors="replace") as f:
        for _, line in zip(range(500), f):
            try:
                cwd = json.loads(line).get("cwd")
            except ValueError:
                continue
            if cwd:
                return Path(cwd)
    return None


def session_kb_root(payload: dict) -> Path:
    """The KB a hook payload's session belongs to: KB_ROOT env, else the launch directory's, else the payload cwd's."""
    if os.getenv("KB_ROOT"):
        return Path(os.environ["KB_ROOT"])
    start = launch_cwd(payload.get("transcript_path")) or Path(payload.get("cwd") or Path.cwd())
    return kb_root(start)


def kb_of_file(file_path: str) -> Path | None:
    """The KB a file belongs to (the path up to `.claude/knowledge`), or None."""
    marker = "/.claude/knowledge/"
    return Path(file_path.split(marker)[0] + marker.rstrip("/")) if marker in file_path else None


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _layer(raw: dict) -> dict:
    """Only the keys this module owns, with the legacy clean.enabled folded into features.clean_nudge."""
    out = {k: dict(raw[k]) for k in ("features", "capture") if isinstance(raw.get(k), dict)}
    if "related_hops" in raw:
        out["related_hops"] = raw["related_hops"]
    clean = raw.get("clean")
    if isinstance(clean, dict) and "enabled" in clean and "clean_nudge" not in out.get("features", {}):
        out.setdefault("features", {})["clean_nudge"] = bool(clean["enabled"])
    return out


def _env_layer() -> dict:
    if os.getenv("KB_CAPTURE_FORK") or os.getenv("KB_HOOKS", "").lower() == "off":
        return {"features": {k: OFF.get(k, False) for k in DEFAULTS["features"]}}
    return {"features": {"router": os.environ["KB_ROUTER"]}} if os.getenv("KB_ROUTER") else {}


def _layers(root: Path) -> list[tuple[str, dict]]:
    return [("default", DEFAULTS), ("global", _layer(_read(GLOBAL_CONFIG))),
            ("repo", _layer(_read(Path(root) / ".kb" / "config.json"))), ("env", _env_layer())]


def load(root: Path) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    for _, layer in _layers(root)[1:]:
        for key, value in layer.items():
            if isinstance(value, dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def feature(name: str, root: Path):
    return load(root)["features"][name]


def enabled(name: str, root: Path) -> bool:
    """True when the KB exists and the feature is not switched off."""
    if not (Path(root) / "index.json").exists():
        return False
    value = feature(name, root)
    return value not in (False, "off")


def show(root: Path) -> str:
    lines = [f"KB root: {root}" + ("" if (Path(root) / "index.json").exists() else "  (no index.json: all off)")]
    layers = _layers(root)
    for section in ("features", "capture"):
        for key in DEFAULTS[section]:
            source, value = next((n, l[section][key]) for n, l in reversed(layers) if key in l.get(section, {}))
            lines.append(f"{section}.{key} = {value}  ({source})" if section == "capture" else f"{key} = {value}  ({source})")
    return "\n".join(lines)


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["show"]:
        print(show(kb_root(Path(args[1]) if len(args) > 1 else None)))
        return 0
    if args[:1] == ["root"]:
        root = kb_root()
        name = args[args.index("--feature") + 1] if "--feature" in args else None
        ok = enabled(name, root) if name else (root / "index.json").exists()
        if ok:
            print(root)
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
