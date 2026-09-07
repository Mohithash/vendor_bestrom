"""Unit naming, the job registry and the parsers. systemctl is never called."""

from __future__ import annotations

from pathlib import Path

from bestrom_mcp.jobs import (
    JobRecord,
    Registry,
    make_unit_name,
    parse_build_exit,
    parse_show,
)

FIXTURES = Path(__file__).parent / "fixtures"

SHOW_OUTPUT = """ActiveState=failed
SubState=failed
ExecMainStatus=3
Result=exit-code
LoadState=loaded
"""


def test_unit_name_carries_the_prefix_and_is_shell_safe() -> None:
    unit = make_unit_name("bestrom-build-", "20260907-103000")
    assert unit == "bestrom-build-20260907-103000"
    assert all(c.isalnum() or c in "-_." for c in unit)


def test_unit_name_sanitises_hostile_input() -> None:
    unit = make_unit_name("bestrom-build-", "a b;rm -rf /")
    assert " " not in unit and ";" not in unit and "/" not in unit


def test_parse_show() -> None:
    parsed = parse_show(SHOW_OUTPUT)
    assert parsed["ActiveState"] == "failed"
    assert parsed["ExecMainStatus"] == "3"
    assert parsed["LoadState"] == "loaded"


def test_parse_show_on_a_collected_unit() -> None:
    assert parse_show("") == {}


def test_parse_build_exit_from_a_log_tail() -> None:
    text = (FIXTURES / "build-log-tail.txt").read_text()
    assert parse_build_exit(text) == 3


def test_parse_build_exit_takes_the_last_one() -> None:
    text = "=== x BUILD EXIT: 1 ===\nretrying\n=== y BUILD EXIT: 0 ===\n"
    assert parse_build_exit(text) == 0


def test_parse_build_exit_none_while_running() -> None:
    assert parse_build_exit("[ 42% 100/240] compiling something") is None
    assert parse_build_exit("") is None


def test_registry_round_trips(tmp_path: Path) -> None:
    registry = Registry.load(tmp_path)
    assert registry.newest() is None
    record = JobRecord(
        job_id="bestrom-build-20260907-103000",
        unit="bestrom-build-20260907-103000",
        log_path=str(tmp_path / "build-mcp-1030.log"),
        started_at_utc="2026-09-07T10:30:00Z",
        goal="bestrom",
        jobs=64,
    )
    registry.add(record)

    reloaded = Registry.load(tmp_path)
    assert reloaded.newest() is not None
    assert reloaded.newest().unit == record.unit
    assert reloaded.get(record.job_id).goal == "bestrom"
    assert reloaded.get("nope") is None


def test_registry_survives_a_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "jobs.json").write_text("{not json", encoding="utf-8")
    assert Registry.load(tmp_path).records == []


def test_registry_is_capped(tmp_path: Path) -> None:
    registry = Registry.load(tmp_path)
    for index in range(60):
        registry.add(
            JobRecord(
                job_id=f"bestrom-build-{index:04d}",
                unit=f"bestrom-build-{index:04d}",
                log_path="/dev/null",
                started_at_utc="2026-09-07T10:30:00Z",
            )
        )
    assert len(Registry.load(tmp_path).records) == 50
