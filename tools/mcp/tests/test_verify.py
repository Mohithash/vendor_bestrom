"""The verify profile evaluator, against fixtures.

No out/ tree, no aapt2, no unzip: the evaluator takes injected readers, which is
the whole reason it was split out of the chain scripts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bestrom_mcp.models import VerifyReport
from bestrom_mcp.ops.verify import (
    MARKER_PASS_LINE,
    ProfileError,
    evaluate_profile,
    load_profile,
    render_marker,
    validate_profile,
)

FIXTURES = Path(__file__).parent / "fixtures"
PROFILES = Path(__file__).resolve().parents[1] / "profiles"


class FakeReaders:
    """Readers backed by fixture files instead of out/."""

    def __init__(
        self,
        installed: str = "installed-files-miuicamera.txt",
        buildprop: str = "build.prop.official",
        sepolicy: str = "sepolicy-clean.cil",
        arsc: str = "arsc-seeds-6.txt",
        aapt2: str = "aapt2-vibration-4.txt",
        mtimes: dict[str, float] | None = None,
        zips: tuple[str, int, str, int] = ("new.zip", 2_767_491_225, "old.zip", 2_766_594_503),
    ) -> None:
        self._installed = (FIXTURES / installed).read_text()
        self._buildprop = (FIXTURES / buildprop).read_text()
        self._sepolicy = (FIXTURES / sepolicy).read_text()
        self._arsc = (FIXTURES / arsc).read_text()
        self._aapt2 = (FIXTURES / aapt2).read_text()
        self._mtimes = mtimes if mtimes is not None else {"Freezer.apk": 2000.0, "installed-files.txt": 1000.0}
        self._zips = zips

    def installed_files(self, glob: str) -> str:
        return self._installed

    def arsc_strings(self, apk_glob: str) -> str:
        return self._arsc

    def aapt2_dump(self, apk_glob: str) -> str:
        return self._aapt2

    def read_glob(self, glob: str) -> str:
        return self._buildprop if "build.prop" in glob else self._sepolicy

    def mtime(self, glob: str) -> float | None:
        return self._mtimes.get(glob)

    def zip_sizes(self) -> tuple[str, int, str, int]:
        return self._zips


def _profile() -> dict:
    return load_profile(PROFILES / "peridot.toml")


def _results(readers: FakeReaders) -> dict[str, bool]:
    return {r.id: r.passed for r in evaluate_profile(_profile(), readers)}


def test_shipped_profile_loads_and_has_a_forbidden_check() -> None:
    profile = _profile()
    assert any(c.get("forbidden") for c in profile["check"])


def test_profile_without_a_forbidden_check_is_rejected() -> None:
    data = {
        "name": "presence-only",
        "check": [
            {"id": "a", "kind": "installed_files_count", "pattern": "x", "op": "eq", "expected": 1}
        ],
    }
    with pytest.raises(ProfileError, match="forbidden"):
        validate_profile(data)


def test_profile_with_unknown_kind_is_rejected() -> None:
    data = {"check": [{"id": "a", "kind": "read_the_tea_leaves", "forbidden": True}]}
    with pytest.raises(ProfileError, match="unknown kind"):
        validate_profile(data)


def test_clean_image_passes_every_check() -> None:
    results = _results(FakeReaders())
    assert all(results.values()), [k for k, v in results.items() if not v]


def test_expected_check_does_not_mask_a_failing_forbidden_check() -> None:
    """The image has MiuiCamera AND Aperture staged. The presence check still
    passes; the forbidden check is what catches it."""
    readers = FakeReaders(installed="installed-files-aperture.txt")
    results = _results(readers)
    assert results["miuicamera-apk-present"] is True
    assert results["aperture-apk-absent"] is False
    report = _report(readers)
    assert report.passed is False
    assert "aperture-apk-absent" in report.failed_ids


def test_dirty_sepolicy_fails_the_forbidden_pair() -> None:
    results = _results(FakeReaders(sepolicy="sepolicy-dirty.cil"))
    assert results["fsck-untrusted-sysadmin-absent"] is False
    assert results["fsck-untrusted-neverallow-present"] is False


def test_missing_sound_seed_fails() -> None:
    assert _results(FakeReaders(arsc="arsc-seeds-5.txt"))["sound-seeds"] is False


def test_missing_vibration_default_fails() -> None:
    results = _results(FakeReaders(aapt2="aapt2-vibration-3.txt"))
    assert results["vibration-intensity-defaults"] is False


def test_fabricated_oem_unlock_prop_fails() -> None:
    results = _results(FakeReaders(buildprop="build.prop.unofficial"))
    assert results["oem-unlock-prop-absent"] is False
    assert results["build-status-official"] is False


def test_stale_apk_fails_the_freshness_check() -> None:
    old = {"Freezer.apk": 1000.0, "installed-files.txt": 100_000.0}
    assert _results(FakeReaders(mtimes=old))["freezer-not-stale"] is False


def test_zip_size_delta_matches_the_chain_arithmetic() -> None:
    readers = FakeReaders(zips=("new.zip", 2_767_491_225, "old.zip", 2_766_594_503))
    result = [r for r in evaluate_profile(_profile(), readers) if r.id == "zip-size-sane"][0]
    expected = int((2_767_491_225 - 2_766_594_503) / 1048576)
    assert result.actual.startswith(f"{expected} MB")
    assert result.passed


def test_zip_size_delta_rejects_a_huge_swing() -> None:
    readers = FakeReaders(zips=("new.zip", 2_767_491_225, "old.zip", 2_000_000_000))
    result = [r for r in evaluate_profile(_profile(), readers) if r.id == "zip-size-sane"][0]
    assert not result.passed


def _report(readers: FakeReaders) -> VerifyReport:
    results = evaluate_profile(_profile(), readers)
    passed = all(r.passed for r in results)
    return VerifyReport(
        profile="peridot",
        checks=results,
        passed=passed,
        failed_ids=[r.id for r in results if not r.passed],
        marker_line=MARKER_PASS_LINE if passed else "",
    )


def test_marker_line_is_empty_unless_every_check_passed() -> None:
    assert _report(FakeReaders()).marker_line == MARKER_PASS_LINE
    assert _report(FakeReaders(installed="installed-files-aperture.txt")).marker_line == ""


def test_marker_text_carries_the_literal_only_on_success() -> None:
    good = render_marker(_report(FakeReaders()), "old.zip", 1)
    bad = render_marker(_report(FakeReaders(sepolicy="sepolicy-dirty.cil")), "old.zip", 1)
    assert MARKER_PASS_LINE in good
    assert MARKER_PASS_LINE not in bad
    assert "VERIFY FAILED" in bad


def test_only_subset_runs_named_checks() -> None:
    results = evaluate_profile(_profile(), FakeReaders(), only=["sound-seeds"])
    assert [r.id for r in results] == ["sound-seeds"]


# -- verify_image itself, not a reimplementation of its logic ------------


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A tree holding nothing but a 1 KB fake package, plus an empty logs dir."""
    from dataclasses import replace as dc_replace

    from bestrom_mcp.config import load_config

    tree = tmp_path / "tree"
    out = tree / "out" / "target" / "product" / "peridot"
    out.mkdir(parents=True)
    (out / "BestROM-3.0-peridot-20260907-1010-OFFICIAL.zip").write_bytes(b"x" * 1024)
    logs = tmp_path / "logs"
    logs.mkdir()
    cfg = load_config(environ={"BESTROM_TREE": str(tree)})
    cfg = dc_replace(
        cfg,
        tree=dc_replace(cfg.tree, logs_dir=logs),
        verify=dc_replace(cfg.verify, marker_dir=logs),
        safety=dc_replace(cfg.safety, allowlist_roots=(tree, logs)),
    )
    return cfg, logs


def test_a_subset_run_writes_no_marker(sandbox) -> None:
    """zip-size-sane passes on its own with no previous zip. Writing the gate
    from that one green check is how a 1 KB file became a release candidate."""
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    report = verify_image(cfg, checks=["zip-size-sane"], write_marker=True)
    assert report.partial is True
    assert report.passed is False
    assert report.marker_line == ""
    assert report.marker_path == ""
    assert list(logs.glob("*.done")) == []
    assert "partial run" in report.note


def test_a_subset_run_still_reports_its_checks(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, _logs = sandbox
    report = verify_image(cfg, checks=["zip-size-sane"])
    assert report.checks_run == ["zip-size-sane"]
    assert [c.id for c in report.checks] == ["zip-size-sane"]


def test_a_full_run_over_an_empty_tree_fails_and_writes_a_failure_marker(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    report = verify_image(cfg, write_marker=True)
    assert report.partial is False
    assert report.passed is False
    marker = logs / "chain-peridot-build.done"
    assert marker.is_file()
    text = marker.read_text()
    assert MARKER_PASS_LINE not in text
    assert "VERIFY FAILED" in text


def test_marker_name_must_be_a_chain_marker(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    (logs / "chain-hardening-notes.txt").write_text("real notes\n", encoding="utf-8")
    report = verify_image(cfg, write_marker=True, marker_name="chain-hardening-notes.txt")
    assert report.marker_path == ""
    assert "chain-<slug>-build.done" in report.note
    assert (logs / "chain-hardening-notes.txt").read_text() == "real notes\n"


def test_marker_name_must_name_a_configured_chain(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    report = verify_image(cfg, write_marker=True, marker_name="chain-wildcat-build.done")
    assert report.marker_path == ""
    assert "not a configured chain" in report.note
    assert not (logs / "chain-wildcat-build.done").exists()


def test_a_configured_chain_marker_is_allowed(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    report = verify_image(cfg, write_marker=True, marker_name="chain-hardening-build.done")
    assert report.marker_path == str(logs / "chain-hardening-build.done")


def test_the_marker_records_how_many_checks_ran(sandbox) -> None:
    from bestrom_mcp.ops.verify import verify_image

    cfg, logs = sandbox
    verify_image(cfg, write_marker=True)
    text = (logs / "chain-peridot-build.done").read_text()
    total = len(_profile()["check"])
    assert f"checks run: {total} of {total}" in text
    assert "verify profile: peridot" in text
