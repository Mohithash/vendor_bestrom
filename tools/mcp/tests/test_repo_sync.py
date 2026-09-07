"""repo_sync's argument surface.

`projects` reaches repo's argv. resolve_allowed alone does not protect it: it
joins the string onto the tree root, so "--force-remove-dirty" resolves to a
path inside the allowlist and is accepted. These tests pin the refusal.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bestrom_mcp.config import load_config
from bestrom_mcp.ops.repo import repo_sync, validate_projects


@pytest.fixture()
def sandbox(tmp_path: Path):
    tree = tmp_path / "tree"
    (tree / "vendor" / "bestrom").mkdir(parents=True)
    logs = tmp_path / "logs"
    logs.mkdir()
    cfg = load_config(environ={"BESTROM_TREE": str(tree)})
    return replace(
        cfg,
        tree=replace(cfg.tree, logs_dir=logs),
        safety=replace(cfg.safety, allowlist_roots=(tree, logs)),
    )


@pytest.mark.parametrize(
    "bad",
    [
        "--force-sync",
        "--force-remove-dirty",
        "-j99",
        "--network-only",
        "vendor/../../etc",
        "vendor/bestrom;rm",
        "vendor bestrom",
    ],
)
def test_option_shaped_projects_are_refused(sandbox, bad: str) -> None:
    result = repo_sync(sandbox, projects=[bad], dry_run=True)
    assert result.refused_reason
    assert bad not in result.command_preview


def test_a_real_project_path_is_accepted(sandbox) -> None:
    rels, refusal = validate_projects(["vendor/bestrom", "frameworks/base"])
    assert refusal == ""
    assert rels == ["vendor/bestrom", "frameworks/base"]


def test_validated_paths_go_after_a_double_dash(sandbox) -> None:
    result = repo_sync(sandbox, projects=["vendor/bestrom"], dry_run=True)
    assert not result.refused_reason
    assert result.command_preview.endswith("-- vendor/bestrom")


def test_a_dry_run_does_not_touch_the_network_by_default(sandbox) -> None:
    """The fetch is opt-in: --network-only on a cold tree is tens of GB."""
    result = repo_sync(sandbox, dry_run=True)
    assert result.fetched is False
    assert "--network-only" not in result.command_preview


def test_a_real_sync_still_needs_confirm(sandbox) -> None:
    result = repo_sync(sandbox, dry_run=False, confirm=False)
    assert "confirm=true" in result.refused_reason
