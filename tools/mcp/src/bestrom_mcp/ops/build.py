"""build_start, build_status, build_errors, build_cancel, build_artifacts."""

from __future__ import annotations

import hashlib
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

from .. import jobs, proc
from ..config import Config
from ..models import (
    Artifacts,
    BuildErrors,
    BuildJob,
    BuildStatus,
    CancelResult,
    ImageFile,
    PreviousRelease,
    ZipInfo,
)
from .env import env_check

GOALS = ("bestrom", "installclean", "otapackage")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
IMAGES = ("boot.img", "vendor_boot.img", "dtbo.img", "vbmeta.img", "super.img", "recovery.img")


def _log_path(cfg: Config, slug: str) -> Path:
    # Seconds, not just %H%M: two builds started in the same minute shared a log.
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    return cfg.tree.logs_dir / f"{cfg.build.log_prefix}{slug}-{stamp}.log"


def official_stamp(cfg: Config) -> tuple[bool, str]:
    """(is OFFICIAL, why). The wrapper decides, not this server.

    build-bestrom-run.sh exports BESTROM_OFFICIAL unconditionally, so an
    inherited value is overwritten before config/branding.mk reads it. A tool
    flag that claimed otherwise would hand back a zip named ...-OFFICIAL.zip,
    which then matches zip_glob and becomes the release candidate.
    """
    script = cfg.tree.root / cfg.build.script
    try:
        text = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return cfg.build.official, f"{script} is unreadable; assuming the configured default"
    if re.search(r"export\s+BESTROM_OFFICIAL=\$\{BESTROM_OFFICIAL", text):
        return cfg.build.official, f"{cfg.build.script} honours an inherited BESTROM_OFFICIAL"
    if re.search(r"export\s+BESTROM_OFFICIAL=true", text):
        return True, (
            f"{cfg.build.script} exports BESTROM_OFFICIAL=true unconditionally, so every "
            "build through this tool is stamped OFFICIAL. Change that line to "
            "${BESTROM_OFFICIAL:-true} to allow test builds."
        )
    return cfg.build.official, ""


def _script(cfg: Config, goal: str, jobs_count: int, installclean: bool, log: Path) -> str:
    tree = shlex.quote(str(cfg.tree.root))
    logq = shlex.quote(str(log))
    lunch = shlex.quote(cfg.build.lunch)
    parts = [f"cd {tree}", f"exec > {logq} 2>&1"]
    clean = (
        f"source build/envsetup.sh >/dev/null 2>&1; "
        f"lunch {lunch} >/dev/null 2>&1; "
        f"m installclean; echo \"installclean rc=$?\""
    )
    if goal == "installclean":
        parts.append(clean)
    else:
        if installclean:
            parts.append(clean)
        parts.append(
            f"TARGET_GOAL={shlex.quote(goal)} J={jobs_count} "
            f"bash {shlex.quote(cfg.build.script)}"
        )
    return "; ".join(parts)


def build_start(
    cfg: Config,
    target: str = "bestrom",
    installclean: bool = False,
    jobs_count: int | None = None,
    log_name: str = "mcp",
    dry_run: bool = True,
) -> BuildJob:
    if target not in GOALS:
        return BuildJob(dry_run=dry_run, refused_reason=f"target must be one of {GOALS}")
    if not SLUG_RE.match(log_name or ""):
        return BuildJob(
            dry_run=dry_run,
            refused_reason="log_name must be a lowercase slug, [a-z0-9-] up to 32 chars",
        )
    jobs_count = int(jobs_count or cfg.build.jobs)
    if not 1 <= jobs_count <= 256:
        return BuildJob(dry_run=dry_run, refused_reason="jobs must be between 1 and 256")

    log = _log_path(cfg, log_name)
    unit = jobs.make_unit_name(cfg.build.unit_prefix)
    script = _script(cfg, target, jobs_count, installclean, log)
    official, official_note = official_stamp(cfg)
    argv = [
        "systemd-run", "--user", f"--unit={unit}", "--collect",
        f"--description=BestROM build {unit}",
        # The build's whole environment comes from build-bestrom-run.sh. This is
        # passed for the case where that script is changed to honour it.
        f"--setenv=BESTROM_OFFICIAL={'true' if official else 'false'}",
        "--", "bash", "-lc", script,
    ]
    preview = " ".join(shlex.quote(a) for a in argv)

    running, which_proc = jobs.build_in_flight()
    if running:
        registry = jobs.Registry.load(cfg.state_dir)
        newest = registry.newest()
        return BuildJob(
            dry_run=dry_run,
            command_preview=preview,
            official=official,
            note=official_note,
            log_path=str(newest.log_path) if newest else "",
            refused_reason=(
                f"a build is already in flight ({which_proc} is running). "
                "Not queueing. "
                + (f"It is writing to {newest.log_path}" if newest else "Log path unknown.")
            ),
        )

    if dry_run:
        return BuildJob(
            dry_run=True,
            command_preview=preview,
            job_id=unit,
            official=official,
            note=official_note,
            log_path=str(log),
            started_at_utc=jobs.utc_now_iso(),
        )

    report = env_check(cfg)
    hard = [b for b in report.blockers if "already in flight" not in b]
    if hard:
        return BuildJob(
            dry_run=False, command_preview=preview, official=official, note=official_note,
            log_path=str(log),
            refused_reason="env_check blockers: " + "; ".join(hard),
        )

    try:
        log.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return BuildJob(
            dry_run=False, command_preview=preview, official=official, note=official_note,
            log_path=str(log),
            refused_reason=(
                f"cannot create the log directory {log.parent}: {exc}. Point [tree] "
                "logs_dir in bestrom.toml, or BESTROM_MCP_TREE_LOGS_DIR, at a "
                "writable directory."
            ),
        )
    result = proc.run(argv, cwd=cfg.tree.root, timeout=120)
    if not result.ok:
        return BuildJob(
            dry_run=False, command_preview=preview, official=official, note=official_note,
            log_path=str(log),
            refused_reason=f"systemd-run failed (rc={result.rc}): {result.err.strip()[:400]}",
        )

    started = jobs.utc_now_iso()
    registry = jobs.Registry.load(cfg.state_dir)
    registry.add(
        jobs.JobRecord(
            job_id=unit, unit=unit, log_path=str(log), started_at_utc=started,
            goal=target, jobs=jobs_count, installclean=installclean,
            command_preview=preview,
        )
    )
    return BuildJob(
        dry_run=False, command_preview=preview, job_id=unit, official=official,
        note=official_note, log_path=str(log), started_at_utc=started,
    )


def build_status(cfg: Config, job_id: str = "", tail_lines: int = 40) -> BuildStatus:
    registry = jobs.Registry.load(cfg.state_dir)
    record = registry.get(job_id) if job_id else registry.newest()
    if record is None:
        return BuildStatus(note="no build has been started through this server")

    show = jobs.unit_show(record.unit)
    load_state = show.get("LoadState", "")
    unit_state = show.get("ActiveState", "")
    note = ""
    if load_state == "not-found" or not unit_state:
        # --collect removes a transient unit when it ends. The log is the
        # authoritative completion record, not systemd.
        unit_state = "gone"
        note = "transient unit already collected; state comes from the log"

    exit_status = None
    if show.get("ExecMainStatus", "").strip().lstrip("-").isdigit():
        exit_status = int(show["ExecMainStatus"])

    tail = proc.tail_file(record.log_path, lines=max(1, min(int(tail_lines), 200)))
    build_exit = jobs.parse_build_exit("\n".join(tail))
    if build_exit is None:
        # BUILD EXIT may already have scrolled past a short tail.
        build_exit = jobs.parse_build_exit("\n".join(proc.tail_file(record.log_path, lines=200)))

    running, _ = jobs.build_in_flight()
    finished = build_exit is not None or (unit_state in {"failed", "inactive", "gone"} and not running)

    elapsed = 0
    try:
        started = datetime.strptime(record.started_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
    except ValueError:
        pass

    return BuildStatus(
        job_id=record.job_id,
        unit_state=unit_state,
        sub_state=show.get("SubState", ""),
        exit_status=exit_status,
        elapsed_s=elapsed,
        build_exit=build_exit,
        finished=finished,
        log_path=record.log_path,
        log_tail=tail,
        note=note,
    )


def newest_log(cfg: Config) -> Path | None:
    logs = sorted(
        cfg.tree.logs_dir.glob(f"{cfg.build.log_prefix}*.log"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
    )
    return logs[-1] if logs else None


def build_errors(
    cfg: Config, job_id: str = "", log_path: str = "", limit: int = 12
) -> BuildErrors:
    limit = max(1, min(int(limit), 50))
    path: Path | None = None
    if log_path:
        path = cfg.resolve_allowed(log_path)
    else:
        registry = jobs.Registry.load(cfg.state_dir)
        record = registry.get(job_id) if job_id else registry.newest()
        if record:
            path = Path(record.log_path)
        else:
            path = newest_log(cfg)
    if path is None or not path.is_file():
        return BuildErrors(log_path=str(path or ""), errors=["no build log found"])

    tail = "\n".join(proc.tail_file(path, lines=200))
    build_exit = jobs.parse_build_exit(tail)

    hits = proc.grep_file(
        path,
        r"^FAILED:|error:|timed out polling",
        exclude=r"warning",
        limit=limit * 4,
    )
    failed: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for line in hits:
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        if line.startswith("FAILED:"):
            failed.append(line)
        else:
            errors.append(line)
    truncated = len(failed) > limit or len(errors) > limit
    return BuildErrors(
        log_path=str(path),
        build_exit=build_exit,
        failed_targets=failed[:limit],
        errors=errors[:limit],
        truncated=truncated,
    )


def build_cancel(cfg: Config, job_id: str, confirm: bool = False) -> CancelResult:
    registry = jobs.Registry.load(cfg.state_dir)
    record = registry.get(job_id)
    if record is None:
        return CancelResult(
            job_id=job_id,
            refused_reason="unknown job: only a unit this server started can be stopped",
        )
    if not record.unit.startswith(cfg.build.unit_prefix):
        return CancelResult(
            job_id=job_id,
            refused_reason=f"unit {record.unit} does not carry the {cfg.build.unit_prefix} prefix",
        )
    if not confirm:
        return CancelResult(
            job_id=record.job_id,
            refused_reason="confirm=true is required to stop a build",
        )
    result = proc.run(["systemctl", "--user", "stop", record.unit], timeout=120)
    show = jobs.unit_show(record.unit)
    return CancelResult(
        job_id=record.job_id,
        stopped=result.ok,
        unit_state=show.get("ActiveState", "gone"),
        refused_reason="" if result.ok else result.err.strip()[:300],
    )


# -- artifacts -----------------------------------------------------------


def read_build_props(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in keys:
                out[key.strip()] = value.strip()
    except OSError:
        pass
    return out


def newest_zip(cfg: Config) -> Path | None:
    zips = [p for p in cfg.tree.out.glob(cfg.build.zip_glob) if p.is_file()]
    zips.sort(key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def zip_info(path: Path | None, sha256: str = "") -> ZipInfo:
    if path is None or not path.is_file():
        return ZipInfo()
    stat = path.stat()
    return ZipInfo(
        name=path.name,
        path=str(path),
        size=stat.st_size,
        size_gb=round(stat.st_size / 1e9, 2),
        mtime=datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        sha256=sha256,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_sha(cfg: Config, name: str) -> str:
    for candidate in (
        cfg.tree.dl_dir / f"{name}.sha256",
        cfg.tree.dl_dir / f"{name}.sha256sum",
        cfg.tree.out / f"{name}.sha256",
    ):
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8").split()[0]
            except (OSError, IndexError):
                continue
    return ""


def build_artifacts(
    cfg: Config, compute_sha256: bool = False, include_images: bool = True
) -> Artifacts:
    target = newest_zip(cfg)
    if target is None:
        return Artifacts(note=f"no {cfg.build.zip_glob} in {cfg.tree.out}")

    sha = sidecar_sha(cfg, target.name)
    sidecar_present = bool(sha)
    if compute_sha256 and not sha:
        sha = sha256_file(target)

    images: list[ImageFile] = []
    if include_images:
        for name in IMAGES:
            candidate = cfg.tree.out / name
            if candidate.is_file():
                images.append(ImageFile(name=name, size=candidate.stat().st_size))

    props = read_build_props(
        cfg.tree.out / "system" / "build.prop",
        (
            "ro.bestrom.version",
            "ro.bestrom.releasetype",
            "ro.bestrom.build.status",
            "ro.build.date.utc",
            "ro.build.fingerprint",
        ),
    )

    zips = sorted(
        (p for p in cfg.tree.out.glob(cfg.build.zip_glob) if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    previous = PreviousRelease()
    if len(zips) >= 2:
        prev = zips[-2]
        previous = PreviousRelease(
            name=prev.name,
            size=prev.stat().st_size,
            delta_mb=int((target.stat().st_size - prev.stat().st_size) / 1048576),
        )

    generic = cfg.tree.out / f"{cfg.tree.out.name}-ota.zip"
    return Artifacts(
        zip=zip_info(target, sha),
        sidecar_sha256_present=sidecar_present,
        generic_ota_zip=str(generic) if generic.is_file() else "",
        images=images,
        build_props=props,
        previous_release=previous,
    )
