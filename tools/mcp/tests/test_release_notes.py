"""release_prepare's file inputs.

notes_path used to be an unbounded, unredacted read of anything in the
allowlist, echoed verbatim into readme_txt - which is the text that reaches the
public SourceForge README.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bestrom_mcp.config import load_config
from bestrom_mcp.ops.release import NOTES_MAX_BYTES, release_prepare

ZIP = "BestROM-3.0-peridot-20260907-1010-OFFICIAL.zip"


@pytest.fixture()
def sandbox(tmp_path: Path):
    tree = tmp_path / "tree"
    out = tree / "out" / "target" / "product" / "peridot"
    out.mkdir(parents=True)
    (out / ZIP).write_bytes(b"x" * 1024)
    logs = tmp_path / "logs"
    logs.mkdir()
    cfg = load_config(environ={"BESTROM_TREE": str(tree)})
    cfg = replace(
        cfg,
        tree=replace(cfg.tree, logs_dir=logs),
        verify=replace(cfg.verify, marker_dir=logs),
        release=replace(cfg.release, ota_repo=logs / "ota", site_repo=logs / "site"),
        safety=replace(cfg.safety, allowlist_roots=(tree, logs)),
    )
    return cfg, tree, logs


def test_notes_path_outside_the_logs_dir_is_refused(sandbox) -> None:
    cfg, tree, _logs = sandbox
    script = tree / "gen-keystore.sh"
    script.write_text("PASSWORD=hunter2\n", encoding="utf-8")
    drafts = release_prepare(cfg, notes_path=str(script), dry_run=True)
    assert drafts.refused_reason
    assert "hunter2" not in drafts.readme_txt


def test_notes_path_with_the_wrong_suffix_is_refused(sandbox) -> None:
    cfg, _tree, logs = sandbox
    script = logs / "gen-keystore.sh"
    script.write_text("PASSWORD=hunter2\n", encoding="utf-8")
    drafts = release_prepare(cfg, notes_path=str(script), dry_run=True)
    assert "must end in" in drafts.refused_reason
    assert "hunter2" not in drafts.readme_txt


def test_a_real_notes_file_is_read(sandbox) -> None:
    cfg, _tree, logs = sandbox
    (logs / "chain-hardening-notes.txt").write_text("Camera\n  * one fix\n", encoding="utf-8")
    drafts = release_prepare(cfg, notes_path=str(logs / "chain-hardening-notes.txt"))
    assert not drafts.refused_reason
    assert "one fix" in drafts.readme_txt


def test_notes_are_scrubbed(sandbox) -> None:
    cfg, _tree, logs = sandbox
    (logs / "n.md").write_text(
        "Notes\n  * token=ghp_abcdefghijklmnopqrstuvwxyz012345\n", encoding="utf-8"
    )
    drafts = release_prepare(cfg, notes_path=str(logs / "n.md"))
    assert "ghp_abcdefghijklmnopqrstuvwxyz012345" not in drafts.readme_txt
    assert "[redacted]" in drafts.readme_txt


def test_inline_notes_are_scrubbed_too(sandbox) -> None:
    cfg, _tree, _logs = sandbox
    drafts = release_prepare(cfg, notes="password: hunter2")
    assert "hunter2" not in drafts.readme_txt


def test_notes_are_capped(sandbox) -> None:
    cfg, _tree, logs = sandbox
    (logs / "big.txt").write_text("A" * (NOTES_MAX_BYTES * 2), encoding="utf-8")
    drafts = release_prepare(cfg, notes_path=str(logs / "big.txt"))
    assert "notes truncated" in drafts.readme_txt
    assert len(drafts.readme_txt) < NOTES_MAX_BYTES + 4096


def test_the_release_header_is_not_hardcoded(sandbox) -> None:
    """No build.prop in the sandbox, so every derived field says so."""
    cfg, _tree, _logs = sandbox
    cfg = replace(cfg, release=replace(cfg.release, kernel="", base=""))
    drafts = release_prepare(cfg, notes="Notes\n  * x")
    assert "Kernel:    (unknown)" in drafts.readme_txt
    assert "platform (unknown), vendor (unknown)" in drafts.readme_txt
    assert drafts.warnings
    assert "6.1.176" not in drafts.readme_txt


def test_the_kernel_line_comes_from_configuration(sandbox) -> None:
    cfg, _tree, _logs = sandbox
    cfg = replace(cfg, release=replace(cfg.release, kernel="6.6.99 GKI, Theettam 9.9"))
    drafts = release_prepare(cfg, notes="Notes\n  * x")
    assert "Kernel:    6.6.99 GKI, Theettam 9.9" in drafts.readme_txt


def test_the_ota_version_comes_from_the_package_name(sandbox) -> None:
    cfg, _tree, _logs = sandbox
    drafts = release_prepare(cfg, notes="Notes\n  * x")
    assert '"version": "3.0"' in drafts.ota_json
    assert drafts.version == "3.0-peridot-20260907-1010-OFFICIAL"
