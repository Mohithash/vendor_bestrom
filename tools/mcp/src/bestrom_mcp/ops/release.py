"""release_prepare, release_publish, changelog_add.

The two gates are copied from the publish chains rather than reinvented, and
they are re-evaluated inside :func:`release_publish` — never trusted from an
earlier call:

1. the build marker contains the literal string ``verify gate passed``;
2. the newest package on disk is the same filename the marker recorded.

Without both, a newer unverified build would ship to every user's Updater.
"""

from __future__ import annotations

import json
import re
import shlex
import textwrap
from pathlib import Path

from .. import jobs, proc
from ..config import Config
from ..models import (
    ChangelogResult,
    PublishResult,
    ReleaseDrafts,
    ReleaseGate,
    StageResult,
)
from ..ops.verify import MARKER_CHECKS_RE, MARKER_PASS_LINE
from ..redact import scrub
from .build import build_artifacts, newest_zip, read_build_props, sidecar_sha, zip_info

# The chain scripts run all four of these unconditionally. There is no
# --stages argument to pass, so the tool does not pretend one exists.
STAGES = ("push", "frs", "ota", "site")
CHAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}\Z")

# release notes are a document, not an arbitrary file read
NOTES_SUFFIXES = (".txt", ".md")
NOTES_MAX_BYTES = 64 * 1024

AI_TRAILER_RE = re.compile(
    r"(?im)^\s*(co-authored-by:\s*claude|.*generated with \[?claude)"
)
PREVZ_RE = re.compile(r"^PREVZ=(\S+)", re.MULTILINE)


def marker_for(cfg: Config, chain: str) -> Path:
    return cfg.verify.marker_dir / f"chain-{chain}-build.done"


def newest_marker(cfg: Config) -> Path | None:
    markers = [
        p for p in cfg.verify.marker_dir.glob("chain-*-build.done") if p.is_file()
    ]
    markers.sort(key=lambda p: p.stat().st_mtime)
    return markers[-1] if markers else None


def read_marker_zip(cfg: Config, chain: str = "") -> str:
    """The package filename a build marker recorded, if any."""
    path = marker_for(cfg, chain) if chain else newest_marker(cfg)
    if path is None or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r"(BestROM-[\w.\-]+\.zip)", text)
    return match.group(1) if match else ""


def evaluate_gates(cfg: Config, chain: str = "") -> ReleaseGate:
    """Both publish gates, computed fresh from disk."""
    path = marker_for(cfg, chain) if chain else newest_marker(cfg)
    gate = ReleaseGate(marker_path=str(path) if path else "")
    if path is None or not path.is_file():
        gate.detail = "no build marker found; run verify_image with write_marker=true"
        return gate
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        gate.detail = f"cannot read marker: {exc}"
        return gate

    gate.verify_marker_ok = MARKER_PASS_LINE in text
    partial = MARKER_CHECKS_RE.search(text)
    if partial and partial.group(1) != partial.group(2):
        gate.verify_marker_ok = False
        gate.detail = (
            f"{path.name} records only {partial.group(1)} of {partial.group(2)} "
            "checks; a partial sweep is not a gate"
        )
        return gate
    target = newest_zip(cfg)
    if target is None:
        gate.detail = f"no {cfg.build.zip_glob} in {cfg.tree.out}"
        return gate
    gate.zip_matches_marker = target.name in text

    reasons = []
    if not gate.verify_marker_ok:
        reasons.append(f"{path.name} does not contain '{MARKER_PASS_LINE}'")
    if not gate.zip_matches_marker:
        reasons.append(
            f"newest package {target.name} is not the one {path.name} verified "
            f"({read_marker_zip(cfg, chain) or 'none recorded'})"
        )
    gate.detail = "; ".join(reasons) if reasons else "both gates green"
    return gate


# -- release_prepare -----------------------------------------------------


def _ota_previous(cfg: Config) -> str:
    catalog = cfg.release.ota_repo / "peridot.json"
    if not catalog.is_file():
        return ""
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
        entries = data.get("response") or []
        if entries:
            return str(entries[0].get("filename", ""))
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""
    return ""


def _stamp_of(name: str) -> str:
    match = re.search(r"(\d{8}-\d{4})", name)
    return match.group(1) if match else ""


def _readme_text(
    cfg: Config,
    version: str,
    name: str,
    size: int,
    sha: str,
    previous: str,
    notes: str,
    unknown: list[str],
) -> str:
    """The SourceForge README header, from build.prop and config, not literals.

    Every field that cannot be determined is printed as (unknown) and named in
    *unknown*, so a 3.1 build cannot ship a README claiming a 3.0 kernel.
    """
    props = read_build_props(
        cfg.tree.out / "system" / "build.prop",
        (
            "ro.build.version.sdk",
            "ro.build.version.release",
            "ro.build.version.security_patch",
            "ro.vendor.build.security_patch",
            "ro.build.fingerprint",
        ),
    )

    def field(value: str, label: str) -> str:
        if value:
            return value
        unknown.append(label)
        return "(unknown)"

    sdk = field(props.get("ro.build.version.sdk", ""), "ro.build.version.sdk")
    android = field(props.get("ro.build.version.release", ""), "ro.build.version.release")
    base = field(cfg.release.base, "[release] base in bestrom.toml")
    kernel = field(cfg.release.kernel, "[release] kernel in bestrom.toml")
    platform_patch = field(
        props.get("ro.build.version.security_patch", ""), "ro.build.version.security_patch"
    )
    vendor_patch = field(
        props.get("ro.vendor.build.security_patch", ""), "ro.vendor.build.security_patch"
    )
    prev_stamp = _stamp_of(previous) or "the previous build"
    heading = f"BestROM {version.split('-')[0]} for POCO F6 (peridot)"
    return (
        f"{heading}\n"
        f"{'=' * len(heading)}\n"
        "\n"
        f"Release:   {version}\n"
        f"Package:   {name} ({size} bytes)\n"
        f"sha256:    {sha or '(not computed - pass compute_sha256)'}\n"
        f"Android:   {android} (SDK {sdk}), {base}\n"
        f"Kernel:    {kernel}\n"
        f"Patch:     platform {platform_patch}, vendor {vendor_patch}\n"
        f"Previous:  {prev_stamp}\n"
        "\n"
        "Flashing\n"
        "--------\n"
        "Boot to recovery, then:\n"
        "\n"
        f"    adb sideload {name}\n"
        "\n"
        "Dirty flash over any earlier build. No wipe required.\n"
        "\n"
        "\n"
        f"Changes since {prev_stamp}\n"
        f"{'-' * (len('Changes since ') + len(prev_stamp))}\n"
        f"{notes.rstrip()}\n"
    )


def _ota_json(cfg: Config, name: str, sha: str, size: int, timestamp: int, version: str) -> str:
    url = (
        f"https://downloads.sourceforge.net/project/"
        f"{cfg.release.sourceforge_project}/peridot/{name}"
    )
    payload = {
        "response": [
            {
                "datetime": timestamp,
                "filename": name,
                "id": sha,
                # Updater.parseJsonUpdate requires "md5". The value is the
                # sha256; the key name is historical and a missing key drops
                # the whole entry, so the app shows no update.
                "md5": sha,
                "romtype": "official",
                "size": size,
                "url": url,
                "version": version,
                "download": url,
                "timestamp": timestamp,
            }
        ]
    }
    return json.dumps(payload, indent=2) + "\n"


def _site_card_diff(cfg: Config, previous: str, name: str, size: int, sha: str) -> list[str]:
    lines: list[str] = []
    gb = f"{size / 1e9:.2f} GB"
    short = sha[:13]
    for path in (cfg.release.site_repo / "docs" / "index.html", cfg.release.pages_dir / "live-index.html"):
        if not path.is_file():
            lines.append(f"{path}: MISSING")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            lines.append(f"{path}: unreadable ({exc})")
            continue
        lines.append(
            f"{path}: replace {previous or '<previous zip>'} -> {name} "
            f"({text.count(previous) if previous else 0} occurrence(s)), "
            f"size -> {gb}, sha prefix -> {short or '<sha>'}"
        )
    return lines


def _clean_notes(text: str) -> str:
    """Redact and cap anything that becomes public release text.

    notes_path used to be an unbounded, unredacted read of any file in the
    allowlist, echoed straight back into readme_txt - which reaches the
    SourceForge README. Both halves are fixed here: one scrub pass, one cap.
    """
    encoded = text.encode("utf-8", "replace")
    if len(encoded) > NOTES_MAX_BYTES:
        text = encoded[:NOTES_MAX_BYTES].decode("utf-8", "ignore")
        text += f"\n... [notes truncated at {NOTES_MAX_BYTES} bytes]\n"
    return scrub(text)


def _read_notes_file(cfg: Config, notes_path: str) -> tuple[str, str]:
    """(text, refusal). Notes live in the logs directory and nowhere else."""
    try:
        path = cfg.resolve_allowed(notes_path, must_exist=True)
    except (ValueError, OSError) as exc:
        return "", str(exc)
    logs = cfg.tree.logs_dir.resolve()
    try:
        path.relative_to(logs)
    except ValueError:
        return "", (
            f"notes_path must be a release-notes file under {logs} "
            f"(the chain-<name>-notes.txt shape); {path} is not"
        )
    if path.suffix.lower() not in NOTES_SUFFIXES:
        return "", f"notes_path must end in {' or '.join(NOTES_SUFFIXES)}; got {path.suffix!r}"
    try:
        return path.read_text(encoding="utf-8", errors="replace"), ""
    except OSError as exc:
        return "", str(exc)


def release_prepare(
    cfg: Config,
    notes: str = "",
    notes_path: str = "",
    previous: str = "",
    dry_run: bool = True,
) -> ReleaseDrafts:
    if notes_path:
        notes, refusal = _read_notes_file(cfg, notes_path)
        if refusal:
            return ReleaseDrafts(dry_run=dry_run, refused_reason=refusal)
    if not notes.strip():
        return ReleaseDrafts(dry_run=dry_run, refused_reason="notes (or notes_path) is required")
    notes = _clean_notes(notes)

    target = newest_zip(cfg)
    if target is None:
        return ReleaseDrafts(
            dry_run=dry_run, refused_reason=f"no {cfg.build.zip_glob} in {cfg.tree.out}"
        )

    artifacts = build_artifacts(cfg, compute_sha256=False, include_images=False)
    sha = artifacts.zip.sha256 or sidecar_sha(cfg, target.name)
    size = target.stat().st_size
    version = target.name[len("BestROM-") :].removesuffix(".zip")
    previous = previous or _ota_previous(cfg) or artifacts.previous_release.name

    props = read_build_props(cfg.tree.out / "system" / "build.prop", ("ro.build.date.utc",))
    try:
        timestamp = int(props.get("ro.build.date.utc", "0")) or int(target.stat().st_mtime)
    except ValueError:
        timestamp = int(target.stat().st_mtime)

    unknown: list[str] = []
    readme = _readme_text(cfg, version, target.name, size, sha, previous, notes, unknown)
    changelog_entry = (
        f"{version}\n{'=' * len(version)}\n\n{notes.rstrip()}\n"
    )
    drafts = ReleaseDrafts(
        version=version,
        zip=zip_info(target, sha),
        readme_txt=readme,
        changelog_entry=changelog_entry,
        ota_json=_ota_json(cfg, target.name, sha, size, timestamp, version.split("-")[0]),
        site_card_diff=_site_card_diff(cfg, previous, target.name, size, sha),
        gate=evaluate_gates(cfg),
        warnings=(
            [f"not determined, printed as (unknown): {', '.join(unknown)}"] if unknown else []
        ),
        dry_run=dry_run,
    )

    if not dry_run:
        staging = cfg.tree.logs_dir / "sf-release" / "peridot"
        try:
            staging = cfg.resolve_allowed(staging)
            staging.mkdir(parents=True, exist_ok=True)
            (staging / "README.txt").write_text(readme, encoding="utf-8")
            (staging / "peridot.json.draft").write_text(drafts.ota_json, encoding="utf-8")
            (staging / "changelog-entry.draft").write_text(changelog_entry, encoding="utf-8")
            drafts.written_paths = [
                str(staging / "README.txt"),
                str(staging / "peridot.json.draft"),
                str(staging / "changelog-entry.draft"),
            ]
        except (ValueError, OSError) as exc:
            drafts.refused_reason = f"drafts not written: {exc}"
    return drafts


# -- release_publish -----------------------------------------------------


def chain_script_problems(cfg: Config, script: Path, previous_zip: str) -> tuple[str, list[str]]:
    """(refusal, warnings) from reading the chain script before running it.

    The chain scripts are edited per release: PREVZ, the notes path and the OTA
    commit body are literals in them. Re-running a stale one pushes and uploads
    correctly but sed-replaces a package name that is no longer on the site,
    leaving a stale release card and the previous release's description.
    """
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"cannot read {script}: {exc}", []

    warnings: list[str] = []
    match = PREVZ_RE.search(text)
    if match and previous_zip and match.group(1) != previous_zip:
        return (
            f"{script.name} still has PREVZ={match.group(1)} but the previous "
            f"package is {previous_zip}. Its site-card sed would match nothing "
            "and its OTA commit body is the previous release's. Update the "
            "script before publishing.",
            warnings,
        )
    if AI_TRAILER_RE.search(text):
        warnings.append(
            f"{script.name} commits an AI attribution trailer into the OTA and "
            "site repos - the same trailer commit_message_check flags as "
            "'ai-trailer'. Strip it from the script."
        )
    return "", warnings


def release_publish(
    cfg: Config,
    chain: str,
    confirm: bool = False,
    dry_run: bool = True,
) -> PublishResult:
    """Run chain-<chain>-publish.sh. All four stages, always: see STAGES."""
    if not CHAIN_RE.match(chain or ""):
        return PublishResult(dry_run=dry_run, refused_reason="chain must be a lowercase slug")
    if chain not in cfg.release.chains:
        return PublishResult(
            dry_run=dry_run,
            refused_reason=f"unknown chain {chain!r}; configured chains are {list(cfg.release.chains)}",
        )
    stages = list(STAGES)

    script = cfg.tree.logs_dir / f"chain-{chain}-publish.sh"
    argv = ["bash", str(script)]
    preview = " ".join(shlex.quote(a) for a in argv)
    gates = evaluate_gates(cfg, chain)

    def refuse(reason: str, warnings: list[str] | None = None) -> PublishResult:
        return PublishResult(
            dry_run=dry_run, gates=gates, planned_stages=stages, command_preview=preview,
            warnings=warnings or [], refused_reason=reason,
        )

    if not cfg.safety.enable_publish:
        return refuse(
            "publishing is disabled in this configuration (safety.enable_publish=false)"
        )
    if not script.is_file():
        return refuse(f"no publish script at {script}")
    if not (gates.verify_marker_ok and gates.zip_matches_marker):
        return refuse(f"gate failed: {gates.detail}")

    previous_zip = _ota_previous(cfg) or build_artifacts(
        cfg, compute_sha256=False, include_images=False
    ).previous_release.name
    problem, warnings = chain_script_problems(cfg, script, previous_zip)
    if problem:
        return refuse(problem, warnings)

    if dry_run:
        return PublishResult(
            dry_run=True, gates=gates, planned_stages=stages, command_preview=preview,
            warnings=warnings,
            stage_results=[
                StageResult(stage=s, status="planned", detail="dry run; nothing was pushed")
                for s in stages
            ],
        )
    if not confirm:
        return refuse(
            "confirm=true is required: this pushes 7 repos, uploads to "
            "SourceForge and updates the OTA catalog every user's Updater reads",
            warnings,
        )

    try:
        with jobs.ExclusiveLock(cfg.state_dir, "release-publish"):
            result = proc.run(
                argv, cwd=cfg.tree.logs_dir, timeout=cfg.release.publish_timeout_s
            )
    except jobs.LockHeld as exc:
        return refuse(str(exc), warnings)

    marker = cfg.verify.marker_dir / f"chain-{chain}-publish.done"
    stage_results: list[StageResult] = []
    marker_text = ""
    if marker.is_file():
        try:
            marker_text = marker.read_text(encoding="utf-8", errors="replace")
        except OSError:
            marker_text = ""
    for stage, needle in (
        ("push", "== push =="),
        ("frs", "frs upload"),
        ("ota", "ota push"),
        ("site", "site push"),
    ):
        status = "unknown"
        detail = ""
        if needle in marker_text:
            failed = "FAILED" in marker_text.split(needle, 1)[1][:400]
            status = "failed" if failed else "ok"
            detail = "see the publish marker"
        stage_results.append(
            StageResult(stage=stage, status=status, detail=detail, log_path=str(marker))
        )

    if result.timed_out:
        warnings.append(
            f"the chain exceeded {cfg.release.publish_timeout_s}s and its process "
            "group was killed; the marker says how far it got"
        )
    return PublishResult(
        dry_run=False,
        gates=gates,
        planned_stages=stages,
        stage_results=stage_results,
        warnings=warnings,
        command_preview=preview,
        refused_reason="" if result.ok else f"publish script exited {result.rc}; see {marker}",
    )


# -- changelog_add -------------------------------------------------------

UNRELEASED_HEADING = "Unreleased (next build)"


def changelog_add(
    cfg: Config, section: str, bullets: list[str], dry_run: bool = True
) -> ChangelogResult:
    path = cfg.tree.root / "vendor" / "bestrom" / "CHANGELOG.md"
    if not section.strip():
        return ChangelogResult(dry_run=dry_run, path=str(path), refused_reason="section is required")
    bullets = [b.strip() for b in bullets if b.strip()]
    if not bullets:
        return ChangelogResult(
            dry_run=dry_run, path=str(path), refused_reason="at least one bullet is required"
        )
    if not path.is_file():
        return ChangelogResult(dry_run=dry_run, path=str(path), refused_reason=f"{path} not found")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ChangelogResult(dry_run=dry_run, path=str(path), refused_reason=str(exc))

    block = [section.strip()]
    for bullet in bullets:
        wrapped = textwrap.wrap(bullet, width=72, initial_indent="  * ", subsequent_indent="    ")
        block.extend(wrapped or ["  * "])
    entry = "\n".join(block) + "\n\n"

    lines = text.splitlines(keepends=True)
    insert_at = None
    for index, line in enumerate(lines):
        if line.strip() == UNRELEASED_HEADING:
            # Skip the heading and its ==== underline plus the blank line.
            insert_at = index + 2
            while insert_at < len(lines) and not lines[insert_at].strip():
                insert_at += 1
            break
    if insert_at is None:
        return ChangelogResult(
            dry_run=dry_run, path=str(path),
            refused_reason=f"no '{UNRELEASED_HEADING}' heading in {path}",
        )

    new_text = "".join(lines[:insert_at]) + entry + "".join(lines[insert_at:])
    diff = "\n".join(f"+{line}" for line in entry.rstrip("\n").splitlines())

    if not dry_run:
        try:
            cfg.resolve_allowed(path)
            path.write_text(new_text, encoding="utf-8")
        except (ValueError, OSError) as exc:
            return ChangelogResult(
                dry_run=False, path=str(path), diff=diff, refused_reason=str(exc)
            )

    return ChangelogResult(
        dry_run=dry_run,
        diff=diff,
        path=str(path),
        wrapped_at_72=all(len(line) <= 72 for line in entry.splitlines()),
    )
