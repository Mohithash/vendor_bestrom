"""Bounded subprocess runner.

Every call carries an explicit timeout and captures stdout and stderr into the
result. Nothing is ever inherited: on stdio transport a single stray byte on the
server's stdout corrupts the JSON-RPC stream. Output is size-capped and passed
through :mod:`bestrom_mcp.redact` before it is returned.

Every child runs in its own session, so a timeout kills the whole process group
rather than only the direct child. Without that, a timed-out publish leaves the
rsync to SourceForge and the git pushes running while the tool has already told
the agent it failed, and a retry then runs a second one alongside it.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .redact import scrub

DEFAULT_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 200_000
MAX_BYTES = 8 << 20


@dataclass(frozen=True)
class ProcResult:
    argv: tuple[str, ...]
    rc: int
    out: str
    err: str
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.timed_out

    @property
    def text(self) -> str:
        return self.out if self.out else self.err

    def lines(self) -> list[str]:
        return [line for line in self.out.splitlines() if line]

    @property
    def command(self) -> str:
        return " ".join(shlex.quote(a) for a in self.argv)


def _cap(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    head = text[: MAX_OUTPUT_CHARS // 2]
    tail = text[-MAX_OUTPUT_CHARS // 2 :]
    return f"{head}\n... [{len(text) - MAX_OUTPUT_CHARS} chars elided] ...\n{tail}", True


def _kill_group(child: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the child's whole process group."""
    try:
        pgid = os.getpgid(child.pid)
    except OSError:
        return
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except OSError:
            return
        try:
            child.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _communicate(
    argv: tuple[str, ...],
    cwd: str | Path | None,
    env: dict[str, str],
    stdin_bytes: bytes | None,
    timeout: int,
) -> tuple[bytes, bytes, int, bool]:
    child = subprocess.Popen(  # noqa: S603 - argv list, never shell=True
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = child.communicate(input=stdin_bytes, timeout=timeout)
        return out or b"", err or b"", child.returncode, False
    except subprocess.TimeoutExpired:
        _kill_group(child)
        out = err = b""
        try:
            out, err = child.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return out or b"", err or b"", 124, True


def run(
    argv: list[str] | tuple[str, ...],
    *,
    cwd: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
    stdin_bytes: bytes | None = None,
    check: bool = False,
) -> ProcResult:
    """Run *argv* (never a shell string) and return a captured result."""
    argv = tuple(str(a) for a in argv)
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    # Deterministic parsing of tool output regardless of the maintainer's locale.
    full_env.setdefault("LC_ALL", "C")

    payload = stdin_bytes
    if payload is None and stdin_text is not None:
        payload = stdin_text.encode("utf-8", "replace")

    try:
        out_b, err_b, rc, timed_out = _communicate(argv, cwd, full_env, payload, timeout)
    except FileNotFoundError as exc:
        return ProcResult(argv, 127, "", scrub(str(exc)))
    except OSError as exc:
        return ProcResult(argv, 126, "", scrub(str(exc)))

    capped_out, t1 = _cap(scrub(out_b.decode("utf-8", "replace")))
    capped_err, t2 = _cap(scrub(err_b.decode("utf-8", "replace")))
    result = ProcResult(argv, rc, capped_out, capped_err, timed_out=timed_out, truncated=t1 or t2)
    if check and not result.ok:
        raise RuntimeError(f"{result.command} failed with rc={result.rc}: {result.err[:400]}")
    return result


def run_bytes(
    argv: list[str] | tuple[str, ...],
    *,
    cwd: str | Path | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> tuple[bytes, int, bool]:
    """Run *argv* and return raw stdout. For binary payloads (resources.arsc).

    The text path decodes with errors="replace" and caps the middle out of a
    long result, both of which corrupt a binary stream. Callers that count
    matches in the output need to know when it was cut, so the truncation flag
    comes back with it.
    """
    argv = tuple(str(a) for a in argv)
    env = dict(os.environ)
    env.setdefault("LC_ALL", "C")
    try:
        out_b, _err, rc, timed_out = _communicate(argv, cwd, env, None, timeout)
    except OSError:
        return b"", 126, False
    if len(out_b) > MAX_BYTES:
        return out_b[:MAX_BYTES], rc, True
    return out_b, rc, timed_out


def which(name: str) -> str | None:
    from shutil import which as _which

    return _which(name)


def tail_file(path: str | Path, lines: int = 40, max_line: int = 2000) -> list[str]:
    """Last *lines* lines of a file, read from the end, each truncated.

    Never reads the whole file: the build logs reach 21 MB.
    """
    path = Path(path)
    if not path.is_file():
        return []
    lines = max(1, min(lines, 200))
    block = 8192
    data = b""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            pos = size
            while pos > 0 and data.count(b"\n") <= lines:
                step = min(block, pos)
                pos -= step
                handle.seek(pos)
                data = handle.read(step) + data
    except OSError:
        return []
    text = data.decode("utf-8", "replace")
    out = text.splitlines()[-lines:]
    return [scrub(line[:max_line]) for line in out]


def grep_file(
    path: str | Path,
    pattern: str,
    *,
    limit: int = 50,
    exclude: str | None = None,
    max_line: int = 400,
) -> list[str]:
    """Stream a file and return matching lines. Bounded in both directions."""
    import re

    path = Path(path)
    if not path.is_file():
        return []
    rx = re.compile(pattern)
    ex = re.compile(exclude) if exclude else None
    hits: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not rx.search(line):
                    continue
                if ex and ex.search(line):
                    continue
                hits.append(scrub(line.rstrip("\n")[:max_line]))
                if len(hits) >= limit:
                    break
    except OSError:
        return []
    return hits
