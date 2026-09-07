"""Commit style rules, table-driven.

Asserts rule ids and severities, not just ok/not-ok: a rule that fires under the
wrong id is as bad as one that does not fire.
"""

from __future__ import annotations

import pytest

from bestrom_mcp.ops.style import commit_message_check

GOOD = [
    (
        "vendor: Add the BestROM MCP server\n"
        "\n"
        "Wraps the build, verify, device and release chains as MCP tools so\n"
        "an agent can drive them without ad-hoc shell. Read-only by default.\n"
    ),
    (
        "sepolicy: Drop the CAP_SYS_ADMIN grant to fsck_untrusted\n"
        "\n"
        "AOSP neverallows this and calls the grant a code mistake, so stock\n"
        "and every other peridot ROM deny it.\n"
    ),
    # The two subjects the publish chain writes. They are deliberately not in
    # the "area: Sentence-case" form and must not be flagged.
    "17: 3.0-peridot-20260907-1010-OFFICIAL\n\nSELinux fsck_untrusted stock parity.\n",
    "docs: latest release card (3.0-peridot-20260907-1010-OFFICIAL)\n\nNew package name and size.\n",
]


@pytest.mark.parametrize("message", GOOD)
def test_good_messages_pass(message: str) -> None:
    report = commit_message_check(message)
    assert report.ok, [v.model_dump() for v in report.violations]


def _rules(message: str, strict: bool = False) -> list[tuple[str, str]]:
    report = commit_message_check(message, strict=strict)
    return [(v.rule_id, v.severity) for v in report.violations]


BAD = [
    (
        "subject over 72",
        "vendor: " + "A" * 80 + "\n\nBody.\n",
        ("subject-length-error", "error"),
    ),
    (
        "trailing period",
        "vendor: Add the server.\n\nBody.\n",
        ("subject-trailing-period", "error"),
    ),
    (
        "missing blank second line",
        "vendor: Add the server\nBody on line two.\n",
        ("blank-second-line", "error"),
    ),
    (
        "nine body lines",
        "vendor: Add the server\n\n" + "\n".join(f"Line {i}." for i in range(9)) + "\n",
        ("body-too-long", "error"),
    ),
    (
        "body line over 72",
        "vendor: Add the server\n\n" + "x" * 90 + "\n",
        ("body-line-length", "error"),
    ),
    (
        "emoji",
        "vendor: Add the server \U0001F680\n\nBody.\n",
        ("emoji", "error"),
    ),
    (
        "generated with claude code",
        "vendor: Add the server\n\nBody.\n\nGenerated with [Claude Code]\n",
        ("ai-trailer", "error"),
    ),
    (
        "co-authored-by claude",
        "vendor: Add the server\n\nBody.\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n",
        ("ai-trailer", "error"),
    ),
    (
        "ai vocabulary",
        "vendor: Add the server\n\nA comprehensive and robust refactor.\n",
        ("ai-vocabulary", "error"),
    ),
    (
        "unknown area",
        "quantum: Add the server\n\nBody.\n",
        ("subject-area-unknown", "error"),
    ),
    (
        "lowercase summary",
        "vendor: add the server\n\nBody.\n",
        ("subject-case", "error"),
    ),
    (
        "no subject",
        "",
        ("subject-empty", "error"),
    ),
]


@pytest.mark.parametrize("name,message,expected", BAD, ids=[b[0] for b in BAD])
def test_bad_messages_flagged(name: str, message: str, expected: tuple[str, str]) -> None:
    report = commit_message_check(message)
    assert not report.ok
    assert expected in [(v.rule_id, v.severity) for v in report.violations]


def test_subject_length_warning_is_not_an_error() -> None:
    subject = "vendor: " + "A" * 55
    report = commit_message_check(subject + "\n\nBody.\n")
    assert ("subject-length-warn", "warning") in _rules(subject + "\n\nBody.\n")
    assert report.ok, "a 63-character subject is a warning, not an error"


def test_strict_promotes_warnings() -> None:
    message = "vendor: " + "A" * 55 + "\n\nBody.\n"
    assert commit_message_check(message).ok
    assert not commit_message_check(message, strict=True).ok


def test_body_missing_is_a_warning() -> None:
    assert ("body-missing", "warning") in _rules("vendor: Add the server\n")


def test_suggested_message_round_trips_clean() -> None:
    dirty = (
        "vendor: add a comprehensive server. \U0001F680\n"
        "\n"
        + "x" * 120
        + "\n"
        "\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n"
    )
    report = commit_message_check(dirty)
    assert not report.ok
    second = commit_message_check(report.suggested_message)
    assert second.ok, [v.model_dump() for v in second.violations]
    assert "Claude" not in report.suggested_message
    assert "comprehensive" not in report.suggested_message


# -- strip_ai_trailers ---------------------------------------------------


def test_an_option_shaped_range_is_refused(tmp_path) -> None:
    """--all would otherwise reach git log's argv as an option, not a range."""
    from dataclasses import replace

    from bestrom_mcp.config import load_config
    from bestrom_mcp.ops.style import strip_ai_trailers

    repo = tmp_path / "tree" / "vendor" / "bestrom"
    (repo / ".git").mkdir(parents=True)
    cfg = load_config(environ={"BESTROM_TREE": str(tmp_path / "tree")})
    cfg = replace(cfg, safety=replace(cfg.safety, allowlist_roots=(tmp_path / "tree",)))
    for bad in ("--all", "-n5", "; rm -rf /"):
        scan = strip_ai_trailers(cfg, repo="vendor/bestrom", since=bad)
        assert scan.note == "invalid range", bad


def test_a_real_range_is_accepted(tmp_path) -> None:
    from dataclasses import replace

    from bestrom_mcp.config import load_config
    from bestrom_mcp.ops.style import strip_ai_trailers

    repo = tmp_path / "tree" / "vendor" / "bestrom"
    (repo / ".git").mkdir(parents=True)
    cfg = load_config(environ={"BESTROM_TREE": str(tmp_path / "tree")})
    cfg = replace(cfg, safety=replace(cfg.safety, allowlist_roots=(tmp_path / "tree",)))
    scan = strip_ai_trailers(cfg, repo="vendor/bestrom", since="origin/voltage-17..HEAD")
    assert scan.note != "invalid range"


def test_strip_ai_trailers_has_no_dead_dry_run_parameter() -> None:
    import inspect

    from bestrom_mcp.ops.style import strip_ai_trailers

    assert "dry_run" not in inspect.signature(strip_ai_trailers).parameters
