"""The two publish gates, as predicates against fixture markers.

They are what stands between a half-verified build and every user's Updater, so
they are tested against the exact marker shapes the chain scripts write.
"""

from __future__ import annotations

import inspect
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from bestrom_mcp.config import load_config
from bestrom_mcp.ops.release import (
    STAGES,
    evaluate_gates,
    read_marker_zip,
    release_publish,
)

FIXTURES = Path(__file__).parent / "fixtures"
NEW_ZIP = "BestROM-3.0-peridot-20260907-1010-OFFICIAL.zip"
OLD_ZIP = "BestROM-3.0-peridot-20260906-1056-OFFICIAL.zip"


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A tree with an out/ holding one package and a logs dir holding markers."""
    tree = tmp_path / "tree"
    out = tree / "out" / "target" / "product" / "peridot"
    logs = tmp_path / "logs"
    out.mkdir(parents=True)
    logs.mkdir(parents=True)
    (out / NEW_ZIP).write_bytes(b"x" * 1024)

    cfg = load_config(environ={"BESTROM_TREE": str(tree)})
    cfg = replace(
        cfg,
        tree=replace(cfg.tree, logs_dir=logs),
        verify=replace(cfg.verify, marker_dir=logs),
        safety=replace(cfg.safety, allowlist_roots=(tree, logs)),
    )
    return cfg, logs


def _install_marker(logs: Path, fixture: str, chain: str = "hardening") -> Path:
    target = logs / f"chain-{chain}-build.done"
    shutil.copyfile(FIXTURES / fixture, target)
    return target


def test_marker_without_the_literal_refuses(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-fail.txt")
    gate = evaluate_gates(cfg, "hardening")
    assert gate.verify_marker_ok is False
    assert "verify gate passed" in gate.detail


def test_marker_naming_an_older_zip_refuses(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-oldzip.txt")
    gate = evaluate_gates(cfg, "hardening")
    assert gate.verify_marker_ok is True
    assert gate.zip_matches_marker is False
    assert OLD_ZIP in gate.detail or NEW_ZIP in gate.detail


def test_both_gates_green_when_aligned(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    gate = evaluate_gates(cfg, "hardening")
    assert gate.verify_marker_ok and gate.zip_matches_marker
    assert gate.detail == "both gates green"


def test_no_marker_at_all_refuses(sandbox) -> None:
    cfg, _logs = sandbox
    gate = evaluate_gates(cfg, "hardening")
    assert not gate.verify_marker_ok and not gate.zip_matches_marker


def test_read_marker_zip(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-oldzip.txt")
    assert read_marker_zip(cfg, "hardening") == OLD_ZIP


def test_publish_refuses_on_a_failed_gate_even_with_confirm(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-oldzip.txt")
    (logs / "chain-hardening-publish.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    result = release_publish(cfg, chain="hardening", confirm=True, dry_run=False)
    assert result.refused_reason
    assert not result.stage_results


def test_publish_refuses_without_confirm_even_with_green_gates(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    (logs / "chain-hardening-publish.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    result = release_publish(cfg, chain="hardening", confirm=False, dry_run=False)
    assert "confirm=true is required" in result.refused_reason


def test_publish_dry_run_plans_but_does_not_run(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    (logs / "chain-hardening-publish.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    result = release_publish(cfg, chain="hardening", dry_run=True)
    assert not result.refused_reason
    assert [s.status for s in result.stage_results] == ["planned"] * 4


def test_publish_rejects_an_unknown_chain(sandbox) -> None:
    cfg, _logs = sandbox
    assert "unknown chain" in release_publish(cfg, chain="wildcat").refused_reason


def test_publish_takes_no_stage_argument(sandbox) -> None:
    """The chain scripts run all four stages and take no arguments, so a
    `stages` subset would be a control the tool could not enforce."""
    assert "stages" not in inspect.signature(release_publish).parameters

    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    (logs / "chain-hardening-publish.sh").write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    result = release_publish(cfg, chain="hardening", dry_run=True)
    assert result.planned_stages == list(STAGES)


def test_a_partial_verify_marker_fails_the_gate(sandbox) -> None:
    cfg, logs = sandbox
    (logs / "chain-hardening-build.done").write_text(
        f"build ok: {NEW_ZIP} (1024 bytes)\n"
        "verify profile: peridot\n"
        "checks run: 1 of 18\n"
        "verify gate passed\n",
        encoding="utf-8",
    )
    gate = evaluate_gates(cfg, "hardening")
    assert gate.verify_marker_ok is False
    assert "1 of 18" in gate.detail


def test_publish_refuses_a_chain_script_naming_a_stale_previous(sandbox) -> None:
    cfg, logs = sandbox
    out = cfg.tree.out
    older = out / OLD_ZIP
    older.write_bytes(b"y" * 1024)
    os.utime(older, (1, 1))  # the previous package, not the newest
    _install_marker(logs, "marker-pass.txt")
    (logs / "chain-hardening-publish.sh").write_text(
        "#!/bin/bash\nPREVZ=BestROM-3.0-peridot-20260101-0000-OFFICIAL.zip\nexit 0\n",
        encoding="utf-8",
    )
    result = release_publish(cfg, chain="hardening", confirm=True, dry_run=False)
    assert "PREVZ" in result.refused_reason
    assert not result.stage_results


def test_publish_warns_about_an_ai_trailer_in_the_chain_script(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    (logs / "chain-hardening-publish.sh").write_text(
        "#!/bin/bash\ngit commit -m \"x\n\nCo-Authored-By: Claude Fable 5.1 <n@a.com>\"\n",
        encoding="utf-8",
    )
    result = release_publish(cfg, chain="hardening", dry_run=True)
    assert any("ai attribution" in w.lower() for w in result.warnings)


def test_publish_respects_the_kill_switch(sandbox) -> None:
    cfg, logs = sandbox
    _install_marker(logs, "marker-pass.txt")
    cfg = replace(cfg, safety=replace(cfg.safety, enable_publish=False))
    result = release_publish(cfg, chain="hardening", confirm=True, dry_run=False)
    assert "disabled" in result.refused_reason
