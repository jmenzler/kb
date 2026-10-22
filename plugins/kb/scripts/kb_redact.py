"""Mask secrets and personal data in text that leaves the machine (Jev requests) or lands in logs.

redact(text) -> (masked text, number of masks). Covers provider key formats, bearer tokens, JWTs, private-key
blocks, credentials in URLs, `password=`/`token:`-style assignments, long high-entropy strings, email
addresses, and the exact values of environment variables whose names look secret.
"""
from __future__ import annotations

import os
import re

MASK = "[REDACTED]"
_SECRET_ENV_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.I)
_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b[0-9a-f]{32,}\b"),
    re.compile(r"\b(?=[A-Za-z0-9+/_-]*\d)(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])[A-Za-z0-9+/_-]{40,}={0,2}"),
]
# key = value / key: "value" where the key names a credential; only the value is masked.
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z_]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)"
    r"[A-Za-z_]*)(\s*[:=]\s*)([\"']?)([^\s\"',;]{4,})\3")


def _env_secret_values() -> list[str]:
    return sorted({v for k, v in os.environ.items() if _SECRET_ENV_NAME.search(k) and len(v) >= 8},
                  key=len, reverse=True)


def redact(text: str) -> tuple[str, int]:
    count = 0
    for value in _env_secret_values():
        if value in text:
            count += text.count(value)
            text = text.replace(value, MASK)
    for pattern in _PATTERNS:
        text, n = pattern.subn(MASK, text)
        count += n

    def mask_value(m: re.Match) -> str:
        return m.group(1) + m.group(2) + m.group(3) + MASK + m.group(3)
    text, n = _ASSIGNMENT.subn(mask_value, text)
    return text, count + n
