#!/usr/bin/env python3
"""Local KB-router model server: keeps Qwen3-Embedding loaded and scores messages over a Unix socket.

  uv run --no-project --with sentence-transformers --with numpy python kb-router-daemon.py
Started in the background by kb_router.ensure_daemon() from the prompt hook; exits after IDLE_SECONDS
without requests so the model's ~1.2 GB is released. Protocol: one JSON line in {"text": ...},
one JSON line out {"p": P(route)}.
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
SOCK = Path.home() / ".claude" / "kb-gate" / "router.sock"
IDLE_SECONDS = 2 * 3600


def main() -> None:
    cfg = json.loads((HERE / "kb-router-local.json").read_text())
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(cfg["model"], device=device, model_kwargs={"torch_dtype": torch.float16})
    coef, intercept = np.array(cfg["coef"]), cfg["intercept"]
    model.encode([cfg["prompt"] + "warm up"], normalize_embeddings=True)
    SOCK.parent.mkdir(parents=True, exist_ok=True)
    if SOCK.exists():
        SOCK.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK))
    os.chmod(SOCK, 0o600)
    srv.listen(8)
    srv.settimeout(60)
    last = time.time()
    while time.time() - last < IDLE_SECONDS:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        with conn:
            conn.settimeout(5)
            try:
                req = json.loads(conn.makefile().readline())
                vec = model.encode([cfg["prompt"] + req["text"]], normalize_embeddings=True)[0]
                p = float(1 / (1 + np.exp(-(vec @ coef + intercept))))
                conn.sendall((json.dumps({"p": p}) + "\n").encode())
            except Exception as e:  # noqa: BLE001 — one bad request must not kill the server
                conn.sendall((json.dumps({"error": str(e)[:200]}) + "\n").encode())
        last = time.time()
    srv.close()
    SOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
