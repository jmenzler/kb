#!/usr/bin/env python3
"""Resolve a basename to full KB-relative path(s)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kb_graph import resolve_file

name = sys.argv[1] if len(sys.argv) > 1 else ""
if not name:
    sys.exit(1)
print(resolve_file(name))
