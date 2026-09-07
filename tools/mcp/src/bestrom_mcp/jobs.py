"""Detached build jobs, run as transient ``systemd --user`` units.

A ROM build takes one to three hours and must survive the MCP client
disconnecting and the server exiting. ``nohup setsid`` chains die with the
session; a ``systemd-run --user`` unit does not.

State lives in a JSON registry on disk rather than in the process, so
``build_status`` still works after the server restarts. Units are only ever
stopped by name, from this registry, and only when the name carries the
configured prefix. Nothing here matches a process by command line.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import proc

BUILD_EXIT_RE = re.compile(r"BUILD EXIT:\s*(-?\d+)")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class JobRecord:
    job_id: str
    unit: str
    log_path: str
    started_at_utc: str
    goal: str = ""
    jobs: int = 0
    installclean: bool = False
    command_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Registry:
    path: Path
    records: list[JobRecord] = field(default_factory=list)

    @classmethod
    def load(cls, state_dir: Path) -> "Registry":
        path = Path(state_dir) / "jobs.json"
        records: list[JobRecord] = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = []
            for item in raw if isinstance(raw, list) else []:
                if isinstance(item, dict) and "job_id" in item:
                    known = {f: item.get(f) for f in JobRecord.__dataclass_fields__}
                    known = {k: v for k, v in known.items() if v is not None}
                    try:
                        records.append(JobRecord(**known))
                    except TypeError:
                        continue
        return cls(path=path, records=records)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the registry small: the last 50 jobs are plenty of history.
        payload = [r.to_dict() for r in self.records[-50:]]
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, record: JobRecord) -> None:
        self.records.append(record)
        self.save()

    def newest(self) -> JobRecord | None:
        return self.records[-1] if self.records else None

    def get(self, job_id: str) -> JobRecord | None:
        for record in reversed(self.records):
            if record.job_id == job_id or record.unit == job_id:
                return record
        return None


def systemd_user_ok() -> bool:
    """True when a ``systemd --user`` manager is reachable for this session."""
    if not proc.which("systemctl"):
        return False
    result = proc.run(["systemctl", "--user", "is-system-running"], timeout=15)
    # "degraded" and "starting" are still usable managers; only a hard failure
    # to reach the bus is not.
    text = (result.out + result.err).lower()
    if "failed to connect" in text or "no such file" in text:
        return False
    return bool(result.out.strip())


def unit_show(unit: str) -> dict[str, str]:
    """Parse ``systemctl --user show`` for one transient unit."""
    if not proc.which("systemctl"):
        return {}
    result = proc.run(
        [
            "systemctl",
            "--user",
            "show",
            unit,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "ExecMainStatus",
            "-p",
            "Result",
            "-p",
            "LoadState",
        ],
        timeout=20,
    )
    return parse_show(result.out)


def parse_show(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_build_exit(text: str) -> int | None:
    """Extract N from ``=== <UTC> BUILD EXIT: N ===``, newest wins."""
    found = BUILD_EXIT_RE.findall(text or "")
    if not found:
        return None
    try:
        return int(found[-1])
    except ValueError:
        return None


def build_in_flight() -> tuple[bool, str]:
    """True when soong or ninja is running. Exact process names only.

    ``pgrep -f`` would match this server's own argv and any editor buffer that
    happens to contain the string, so it is never used anywhere in this server.
    """
    for name in ("soong_ui", "ninja"):
        result = proc.run(["pgrep", "-x", name], timeout=15)
        if result.rc == 0 and result.out.strip():
            return True, name
    return False, ""


def make_unit_name(prefix: str, stamp: str | None = None) -> str:
    stamp = stamp or utc_stamp()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", f"{prefix}{stamp}")
    return safe


# -- single-flight locking -----------------------------------------------


class LockHeld(RuntimeError):
    """Raised when another call already holds the lock."""


class ExclusiveLock:
    """A whole-file lock in the state directory, for the long tools.

    repo_sync and release_publish block a worker thread for up to an hour,
    which is longer than the client's own timeout: the client gives up, the
    agent retries, and a second repo sync or a second publish then runs against
    the same tree and the same SourceForge target. The lock is advisory
    (flock), so it is released even if the process dies.
    """

    def __init__(self, state_dir: Path, name: str) -> None:
        self.path = Path(state_dir) / f"{name}.lock"
        self._handle = None

    def __enter__(self) -> "ExclusiveLock":
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._handle.seek(0)
            holder = self._handle.read().strip() or "another call"
            self._handle.close()
            self._handle = None
            raise LockHeld(f"{self.path.stem} is already running ({holder})") from None
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(f"pid {os.getpid()} since {utc_now_iso()}\n")
        self._handle.flush()
        return self

    def __exit__(self, *_exc: object) -> None:
        import fcntl

        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._handle.close()
        self._handle = None
