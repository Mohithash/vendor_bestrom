"""Redaction of credentials from any string that leaves the server.

Pure functions only. Scrubbing is applied in :mod:`bestrom_mcp.proc` (every
subprocess result, ``tail_file`` and ``grep_file``), in the ``bestrom://config``
resource, and wherever a tool reads a file itself — ``release_prepare`` is the
one that does. It is NOT applied automatically at the tool return boundary, so
any new code path that reads a file directly must call :func:`scrub` itself.

It matters because the tree's GitHub auth lives in ``~/.gitconfig``
``http.extraheader`` and SourceForge auth in the ssh agent, and both leak into
ordinary command output.
"""

from __future__ import annotations

import re
from typing import Any

MASK = "[redacted]"

# Order matters: the more specific patterns run first so a token inside an
# Authorization header is not merely partly masked.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks, whole body.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY----- " + MASK + " -----END PRIVATE KEY-----",
    ),
    # git config http.extraheader lines (the whole value, base64 or not).
    (
        re.compile(r"(http\.extraheader\s*[=:]\s*)\S.*", re.IGNORECASE),
        r"\1" + MASK,
    ),
    # HTTP Authorization headers, however they are spelled.
    (
        re.compile(r"(AUTHORIZATION\s*:\s*)(\S+\s+)?\S+", re.IGNORECASE),
        r"\1" + MASK,
    ),
    # GitHub tokens in every documented prefix.
    (
        re.compile(r"\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}"),
        MASK,
    ),
    # Credentials embedded in a URL.
    (
        re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"),
        r"\1" + MASK + "@",
    ),
    (
        re.compile(r"(https?://)x-access-token:[^@\s]+@"),
        r"\1" + MASK + "@",
    ),
    # key=value secrets on a command line or in an env dump.
    (
        re.compile(
            r"\b(token|password|passwd|secret|api[_-]?key|access[_-]?key)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        ),
        r"\1\2" + MASK,
    ),
    # ssh private key paths. The public key is harmless but not interesting.
    (
        re.compile(r"(/[^\s\"']*/\.ssh/)[A-Za-z0-9_.-]+"),
        r"\1" + MASK,
    ),
    # ssh-rsa / ssh-ed25519 key material.
    (
        re.compile(r"\b(ssh-(?:rsa|ed25519|dss))\s+[A-Za-z0-9+/=]{40,}"),
        r"\1 " + MASK,
    ),
]


def scrub(text: str) -> str:
    """Return *text* with every known credential shape masked."""
    if not text:
        return text
    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def scrub_lines(lines: list[str]) -> list[str]:
    return [scrub(line) for line in lines]


def scrub_any(value: Any) -> Any:
    """Recursively scrub strings inside lists, tuples and dicts."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [scrub_any(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub_any(v) for v in value)
    if isinstance(value, dict):
        return {k: scrub_any(v) for k, v in value.items()}
    return value
