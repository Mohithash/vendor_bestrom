"""Subprocess discipline.

A timeout used to kill only the direct child, so a timed-out publish left the
rsync to SourceForge and the git pushes running while the agent was told it had
failed - and a retry then ran a second one alongside it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from bestrom_mcp import proc


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_a_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    pidfile = tmp_path / "grandchild.pid"
    result = proc.run(
        ["bash", "-c", f'sleep 60 & echo $! > {pidfile}; wait'],
        timeout=1,
    )
    assert result.timed_out is True
    assert result.rc == 124
    assert pidfile.is_file()
    grandchild = int(pidfile.read_text().strip())
    for _ in range(50):
        if not _alive(grandchild):
            break
        time.sleep(0.1)
    assert not _alive(grandchild), "the grandchild outlived the timeout"


def test_a_normal_run_still_captures_output() -> None:
    result = proc.run(["echo", "hello"])
    assert result.ok
    assert result.out.strip() == "hello"


def test_stdin_bytes_reaches_the_child() -> None:
    result = proc.run(["cat"], stdin_bytes=b"binary\x00payload")
    assert "binary" in result.out


def test_run_bytes_returns_raw_output() -> None:
    blob, rc, truncated = proc.run_bytes(["printf", "\\x01\\x02\\x03"])
    assert rc == 0
    assert truncated is False
    assert blob == b"\x01\x02\x03"


def test_a_missing_binary_is_a_result_not_an_exception() -> None:
    result = proc.run(["definitely-not-a-real-binary-xyz"])
    assert result.rc == 127
    assert not result.ok
