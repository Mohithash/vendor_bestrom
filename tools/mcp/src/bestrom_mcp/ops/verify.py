"""verify_image and the declarative profile evaluator.

The gate that used to be copy-pasted into every ``chain-*-verify.sh`` lives here
as data (``profiles/<name>.toml``) plus a pure evaluator. The evaluator takes a
*readers* object, so it can be tested without an ``out/`` tree, without aapt2
and without unzip.

The one rule a profile must obey: it has to contain at least one forbidden
check. A gate that only asserts "the thing we want is present" passes a broken
image, which is how a build once shipped with both the old and the new camera
staged in ``out/``.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .. import proc
from ..config import Config
from ..models import CheckResult, VerifyReport

KINDS = (
    "installed_files_count",
    "arsc_string_count",
    "aapt2_resource_count",
    "sepolicy_grep",
    "buildprop_value",
    "apk_mtime_after",
    "zip_size_delta",
)

OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "le": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}

MARKER_PASS_LINE = "verify gate passed"

# The marker is what release_publish trusts, so its name is not free-form: it
# has to be the chain marker for a configured chain (or for the profile being
# run). Anything else could overwrite another chain's gate, the release notes
# the publish chain cats into the SourceForge README, or a build log.
MARKER_NAME_RE = re.compile(r"chain-[a-z0-9][a-z0-9-]{0,31}-build\.done")
MARKER_CHECKS_RE = re.compile(r"^checks run: (\d+) of (\d+)$", re.MULTILINE)


class ReaderError(OSError):
    """Raised when a reader cannot return a whole, trustworthy input."""


class ProfileError(ValueError):
    """Raised when a profile is malformed or unsafe."""


class Readers(Protocol):
    """Everything the evaluator needs from the outside world."""

    def installed_files(self, glob: str) -> str: ...

    def arsc_strings(self, apk_glob: str) -> str: ...

    def aapt2_dump(self, apk_glob: str) -> str: ...

    def read_glob(self, glob: str) -> str: ...

    def mtime(self, glob: str) -> float | None: ...

    def zip_sizes(self) -> tuple[str, int, str, int]: ...


# -- profile loading -----------------------------------------------------


def load_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProfileError(f"no such profile: {path}")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"invalid TOML in {path}: {exc}") from exc
    return validate_profile(data, str(path))


def validate_profile(data: dict[str, Any], origin: str = "<profile>") -> dict[str, Any]:
    checks = data.get("check") or []
    if not isinstance(checks, list) or not checks:
        raise ProfileError(f"{origin}: profile has no [[check]] entries")

    ids: set[str] = set()
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ProfileError(f"{origin}: check #{index} is not a table")
        cid = check.get("id")
        if not cid:
            raise ProfileError(f"{origin}: check #{index} has no id")
        if cid in ids:
            raise ProfileError(f"{origin}: duplicate check id {cid!r}")
        ids.add(cid)
        kind = check.get("kind")
        if kind not in KINDS:
            raise ProfileError(f"{origin}: check {cid!r} has unknown kind {kind!r}")
        op = check.get("op", "eq")
        if op not in OPS:
            raise ProfileError(f"{origin}: check {cid!r} has unknown op {op!r}")

    if not any(bool(c.get("forbidden")) for c in checks):
        raise ProfileError(
            f"{origin}: profile has no forbidden check. A gate that only asserts "
            "presence passes a broken image; every profile must assert at least "
            "one thing is absent."
        )
    return data


# -- pure evaluation -----------------------------------------------------


def _count_matches(text: str, pattern: str, ignore_case: bool, exclude: str | None) -> int:
    flags = re.IGNORECASE if ignore_case else 0
    rx = re.compile(pattern, flags)
    ex = re.compile(exclude, flags) if exclude else None
    count = 0
    for line in text.splitlines():
        if not rx.search(line):
            continue
        if ex and ex.search(line):
            continue
        count += 1
    return count


def _numeric_check(check: dict[str, Any], actual: int) -> tuple[bool, str, str]:
    op = check.get("op", "eq")
    expected = int(check.get("expected", 0))
    passed = OPS[op](actual, expected)
    return passed, str(expected), str(actual)


def evaluate_check(check: dict[str, Any], readers: Readers) -> CheckResult:
    kind = check["kind"]
    result = CheckResult(
        id=check["id"],
        kind=kind,
        description=str(check.get("description", "")),
        op=str(check.get("op", "eq")),
        forbidden=bool(check.get("forbidden", False)),
    )
    try:
        if kind == "installed_files_count":
            text = readers.installed_files(str(check.get("files", "installed-files*.txt")))
            actual = _count_matches(
                text,
                str(check["pattern"]),
                bool(check.get("ignore_case", False)),
                check.get("exclude"),
            )
            result.passed, result.expected, result.actual = _numeric_check(check, actual)

        elif kind == "arsc_string_count":
            text = readers.arsc_strings(str(check["apk"]))
            actual = _count_matches(text, str(check["pattern"]), False, None)
            result.passed, result.expected, result.actual = _numeric_check(check, actual)

        elif kind == "aapt2_resource_count":
            text = readers.aapt2_dump(str(check["apk"]))
            actual = _count_matches(text, str(check["pattern"]), False, None)
            result.passed, result.expected, result.actual = _numeric_check(check, actual)

        elif kind == "sepolicy_grep":
            text = readers.read_glob(str(check["files"]))
            pattern = str(check["pattern"])
            and_pattern = check.get("and_pattern")
            if and_pattern:
                rx = re.compile(pattern)
                rx2 = re.compile(str(and_pattern))
                actual = sum(
                    1 for line in text.splitlines() if rx.search(line) and rx2.search(line)
                )
            else:
                actual = _count_matches(text, pattern, False, None)
            result.passed, result.expected, result.actual = _numeric_check(check, actual)

        elif kind == "buildprop_value":
            text = readers.read_glob(str(check["files"]))
            key = str(check["key"])
            value = ""
            found = False
            for line in text.splitlines():
                name, sep, raw = line.partition("=")
                if sep and name.strip() == key:
                    value = raw.strip()
                    found = True
                    break
            mode = str(check.get("op", "eq"))
            expected = str(check.get("expected", ""))
            if mode == "eq":
                result.passed = found and value == expected
            elif mode == "ne":
                result.passed = value != expected
            else:
                raise ProfileError(f"buildprop_value supports op eq or ne, not {mode!r}")
            result.expected = f"{key}={expected}"
            result.actual = f"{key}={value}" if found else f"{key} absent"

        elif kind == "apk_mtime_after":
            apk_mtime = readers.mtime(str(check["apk"]))
            ref_mtime = readers.mtime(str(check["reference"]))
            tolerance = int(check.get("tolerance_s", 7200))
            if apk_mtime is None or ref_mtime is None:
                result.passed = False
                result.actual = "missing file"
            else:
                result.passed = apk_mtime >= ref_mtime - tolerance
                result.actual = datetime.fromtimestamp(apk_mtime, timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
            result.expected = (
                "not older than "
                + str(check["reference"])
                + f" minus {tolerance}s"
            )

        elif kind == "zip_size_delta":
            name, size, prev_name, prev_size = readers.zip_sizes()
            max_abs = int(check.get("max_abs_mb", 200))
            delta = int((size - prev_size) / 1048576) if prev_size else 0
            result.passed = abs(delta) <= max_abs if prev_size else True
            result.expected = f"|delta| <= {max_abs} MB vs {prev_name or 'no previous zip'}"
            result.actual = f"{delta} MB ({name} {size} vs {prev_size})"

        else:  # pragma: no cover - validate_profile rejects this first
            raise ProfileError(f"unknown kind {kind!r}")

    except ProfileError:
        raise
    except KeyError as exc:
        result.passed = False
        result.detail = f"profile check is missing key {exc}"
    except (OSError, re.error, ValueError) as exc:
        result.passed = False
        result.detail = f"{type(exc).__name__}: {exc}"

    return result


def evaluate_profile(
    profile: dict[str, Any], readers: Readers, only: list[str] | None = None
) -> list[CheckResult]:
    checks = profile.get("check", [])
    if only:
        wanted = set(only)
        checks = [c for c in checks if c.get("id") in wanted]
    return [evaluate_check(check, readers) for check in checks]


# -- the real readers ----------------------------------------------------


class OutDirReaders:
    """Readers backed by the real ``out/target/product/peridot`` tree."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.out = cfg.tree.out
        self._cache: dict[str, str] = {}

    # helpers ---------------------------------------------------------

    def _find(self, glob: str) -> Path | None:
        """The installed copy of a file, not a packaging intermediate.

        A bare rglob for Freezer.apk also matches
        obj/PACKAGING/target_files_intermediates/..., and taking the first
        alphabetically picks that one - so a freshness check would time the
        intermediate rather than what ships.
        """
        matches = self.out.rglob(glob) if "/" not in glob else self.out.glob(glob)
        files = [m for m in matches if m.is_file()]
        if not files:
            return None
        installed = [f for f in files if "/obj/" not in str(f)]
        pool = installed or files
        return max(pool, key=lambda p: p.stat().st_mtime)

    def _read_all(self, glob: str) -> str:
        parts: list[str] = []
        matches = self.out.glob(glob) if "/" in glob or "*" in glob else [self.out / glob]
        for path in sorted(matches):
            if not path.is_file():
                continue
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return "\n".join(parts)

    # protocol --------------------------------------------------------

    def installed_files(self, glob: str) -> str:
        key = f"installed:{glob}"
        if key not in self._cache:
            self._cache[key] = self._read_all(glob)
        return self._cache[key]

    def read_glob(self, glob: str) -> str:
        key = f"glob:{glob}"
        if key not in self._cache:
            text = self._read_all(glob)
            if not text:
                # */etc/selinux/*.cil style patterns need a recursive walk.
                parts = []
                for path in sorted(self.out.rglob(Path(glob).name)):
                    if path.is_file() and path.match(glob):
                        try:
                            parts.append(path.read_text(encoding="utf-8", errors="replace"))
                        except OSError:
                            continue
                text = "\n".join(parts)
            self._cache[key] = text
        return self._cache[key]

    def arsc_strings(self, apk_glob: str) -> str:
        key = f"arsc:{apk_glob}"
        if key in self._cache:
            return self._cache[key]
        apk = self._find(apk_glob)
        if apk is None:
            self._cache[key] = ""
            return ""
        # resources.arsc is binary: it goes through the byte path, because the
        # text path decodes with errors="replace" and elides the middle of a
        # long result, both of which change the string count.
        blob, rc, truncated = proc.run_bytes(["unzip", "-p", str(apk), "resources.arsc"], timeout=120)
        if truncated:
            raise ReaderError(f"resources.arsc from {apk.name} was too large to read whole")
        if rc != 0 and not blob:
            raise ReaderError(f"unzip -p {apk.name} resources.arsc failed (rc={rc})")
        strings = proc.run(["strings"], stdin_bytes=blob, timeout=120)
        if strings.truncated:
            raise ReaderError(f"strings output for {apk.name} was truncated; count unreliable")
        self._cache[key] = strings.out
        return strings.out

    def aapt2_dump(self, apk_glob: str) -> str:
        key = f"aapt2:{apk_glob}"
        if key in self._cache:
            return self._cache[key]
        apk = self._find(apk_glob)
        aapt2 = self.cfg.tree.root / "prebuilts/sdk/tools/linux/bin/aapt2"
        if apk is None or not aapt2.is_file():
            self._cache[key] = ""
            return ""
        result = proc.run([str(aapt2), "dump", "resources", str(apk)], timeout=180)
        if result.truncated:
            raise ReaderError(f"aapt2 dump of {apk.name} was truncated; count unreliable")
        self._cache[key] = result.out
        return result.out

    def mtime(self, glob: str) -> float | None:
        path = self._find(glob)
        if path is None:
            return None
        return path.stat().st_mtime

    def zip_sizes(self) -> tuple[str, int, str, int]:
        zips = sorted(
            (p for p in self.out.glob(self.cfg.build.zip_glob) if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        if not zips:
            return "", 0, "", 0
        newest = zips[-1]
        prev = zips[-2] if len(zips) >= 2 else None
        return (
            newest.name,
            newest.stat().st_size,
            prev.name if prev else "",
            prev.stat().st_size if prev else 0,
        )


# -- the tool ------------------------------------------------------------


def marker_path(cfg: Config, name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", name)
    return cfg.verify.marker_dir / safe


def marker_name_problem(cfg: Config, name: str, profile_name: str) -> str:
    """Why *name* is not an acceptable marker filename, or "" if it is."""
    if not MARKER_NAME_RE.fullmatch(name):
        return (
            f"marker_name {name!r} is not of the form chain-<slug>-build.done; "
            "refusing to write anything else into the logs directory"
        )
    slug = name[len("chain-") : -len("-build.done")]
    allowed = {*cfg.release.chains, profile_name}
    if slug not in allowed:
        return (
            f"marker chain {slug!r} is not a configured chain "
            f"({sorted(allowed)}); refusing to plant one chain's gate as another's"
        )
    return ""


def verify_image(
    cfg: Config,
    profile_name: str = "",
    checks: list[str] | None = None,
    write_marker: bool = False,
    marker_name: str = "",
) -> VerifyReport:
    profile_name = profile_name or cfg.verify.profile
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,31}$", profile_name):
        return VerifyReport(profile=profile_name, note="invalid profile name")
    path = cfg.profiles_path / f"{profile_name}.toml"
    try:
        profile = load_profile(path)
    except ProfileError as exc:
        return VerifyReport(profile=profile_name, note=str(exc))

    all_ids = [str(c.get("id")) for c in profile.get("check", [])]
    readers = OutDirReaders(cfg)
    results = evaluate_profile(profile, readers, only=checks)
    ran_ids = [r.id for r in results]
    partial = set(ran_ids) != set(all_ids)
    name, size, prev_name, prev_size = readers.zip_sizes()
    delta_mb = int((size - prev_size) / 1048576) if prev_size else 0

    from .build import newest_zip, zip_info

    target = newest_zip(cfg)
    info = zip_info(target)

    # A subset run is a diagnostic, never a gate result: passing three of
    # eighteen checks is not "the image is good".
    passed = bool(results) and not partial and all(r.passed for r in results) and target is not None
    failed_ids = [r.id for r in results if not r.passed]
    notes: list[str] = []
    if target is None:
        notes.append(f"no {cfg.build.zip_glob} in {cfg.tree.out}")
    if partial:
        missing = [i for i in all_ids if i not in set(ran_ids)]
        notes.append(
            f"partial run: {len(ran_ids)} of {len(all_ids)} checks "
            f"(skipped {', '.join(missing) or 'none'}). This is a diagnostic, "
            "not a gate result, and no marker can be written from it."
        )

    report = VerifyReport(
        profile=profile_name,
        checks=results,
        checks_run=ran_ids,
        partial=partial,
        passed=passed,
        failed_ids=failed_ids,
        zip=info,
        delta_mb=delta_mb,
        marker_line=MARKER_PASS_LINE if passed else "",
        note=" ".join(notes),
    )

    if write_marker:
        if partial:
            report.note = (
                report.note
                + " marker not written: run the whole profile (drop `checks`) "
                "before writing the gate the publish chain trusts."
            ).strip()
            return report
        target_name = marker_name or f"chain-{profile_name}-build.done"
        problem = marker_name_problem(cfg, target_name, profile_name)
        if problem:
            report.note = (report.note + " marker not written: " + problem).strip()
            return report
        marker = cfg.resolve_allowed(marker_path(cfg, target_name))
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                render_marker(report, prev_name, prev_size, total_checks=len(all_ids)),
                encoding="utf-8",
            )
            report.marker_path = str(marker)
        except OSError as exc:
            report.note = (report.note + f" marker not written: {exc}").strip()
    return report


def render_marker(
    report: VerifyReport, prev_name: str, prev_size: int, total_checks: int | None = None
) -> str:
    """Marker text in the shape the publish chain already greps for.

    The profile name and the count of checks actually run are recorded so
    evaluate_gates can reject a marker that came from a partial sweep.
    """
    total = len(report.checks) if total_checks is None else total_checks
    lines = [
        f"build ok: {report.zip.name} ({report.zip.size} bytes)",
        f"verify profile: {report.profile}",
        f"checks run: {len(report.checks)} of {total}",
        "== verify in image ==",
    ]
    for check in report.checks:
        state = "ok" if check.passed else "FAIL"
        lines.append(
            f"{check.id} [{check.kind}] expected {check.op} {check.expected}, "
            f"got {check.actual} - {state}"
            + (f" ({check.detail})" if check.detail else "")
        )
    lines.append(
        f"zip size vs {prev_name or 'no previous'}: {report.zip.size} vs {prev_size} "
        f"= {report.delta_mb} MB"
    )
    if report.passed:
        lines.append(MARKER_PASS_LINE)
        lines.append(
            f"BUILD+VERIFY DONE {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}: "
            f"{report.zip.name} ({report.zip.size} bytes)"
        )
    else:
        lines.append(
            "VERIFY FAILED ("
            + ", ".join(report.failed_ids)
            + ") - NOT pushing, NOT publishing"
        )
    return "\n".join(lines) + "\n"
