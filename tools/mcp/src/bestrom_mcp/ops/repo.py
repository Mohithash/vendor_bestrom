"""repo_status, manifest_check, repo_sync, tree_repair."""

from __future__ import annotations

import hashlib
import re
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import proc
from ..config import Config
from ..models import (
    CopyfileCheck,
    ManifestCheck,
    ProjectStatus,
    RepairResult,
    RepoStatus,
    SyncResult,
)

# A project argument is a tree-relative path and nothing else. resolve_allowed
# is not enough on its own: it joins the string onto the tree root, so
# "--force-remove-dirty" resolves to <tree>/--force-remove-dirty, passes the
# allowlist, and then reaches repo's argv as an option.
PROJECT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*(/[A-Za-z0-9_][A-Za-z0-9_.+-]*)*")

MANIFEST_REL = "vendor/bestrom/manifest/bestrom.xml"
MIRROR_REL = ".repo/local_manifests/bestrom.xml"

# VoltageOS's own manifest already carries these. repo rejects a duplicate path,
# so adding one here breaks every sync until it is removed again.
FORBIDDEN_PATHS = (
    "hardware/qcom-caf",
    "vendor/qcom/opensource",
    "device/qcom/sepolicy_vndr/sm8650",
    "hardware/nxp",
)

# The <linkfile>/<copyfile> results from build/make. A partial sync loses them
# and the tree then has no build/envsetup.sh at all.
LINKFILES = (
    "CleanSpec.mk",
    "buildspec.mk.default",
    "core",
    "envsetup.sh",
    "target",
    "tools",
)


def manifest_path(cfg: Config) -> Path:
    return cfg.tree.root / MANIFEST_REL


def mirror_path(cfg: Config) -> Path:
    return cfg.tree.root / MIRROR_REL


def parse_manifest(path: Path) -> dict[str, str]:
    """path -> revision for every <project> in the BestROM manifest."""
    if not path.is_file():
        return {}
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError:
        return {}
    out: dict[str, str] = {}
    for project in root.findall("project"):
        p = project.get("path")
        if p:
            out[p] = project.get("revision", "")
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


# -- repo_status ---------------------------------------------------------


def _git(repo: Path, args: list[str], timeout: int = 45) -> proc.ProcResult:
    return proc.run(["git", "-C", str(repo), *args], timeout=timeout)


def _project_status(cfg: Config, rel: str, revisions: dict[str, str]) -> ProjectStatus:
    repo = cfg.tree.root / rel
    status = ProjectStatus(path=rel, manifest_revision=revisions.get(rel, ""))
    if not (repo / ".git").exists():
        status.error = "not a git checkout"
        return status

    status.branch = _git(repo, ["branch", "--show-current"]).out.strip()
    status.head_short = _git(repo, ["rev-parse", "--short=12", "HEAD"]).out.strip()
    porcelain = _git(repo, ["status", "--porcelain"])
    status.dirty_files = len([line for line in porcelain.out.splitlines() if line.strip()])

    rev = status.manifest_revision
    status.branch_matches_manifest = bool(rev) and status.branch == rev

    if status.branch:
        counts = _git(
            repo,
            ["rev-list", "--left-right", "--count", f"{status.branch}...@{{upstream}}"],
        )
        parts = counts.out.split()
        if counts.ok and len(parts) == 2:
            status.ahead, status.behind = int(parts[0]), int(parts[1])
    return status


def repo_status(
    cfg: Config, paths: list[str] | None = None, include_dirty_scan: bool = True
) -> RepoStatus:
    revisions = parse_manifest(manifest_path(cfg))
    publish_set = [spec.split()[0] for spec in cfg.push_projects if spec.split()]
    wanted = list(paths) if paths else list(dict.fromkeys([*publish_set, "vendor/bestrom"]))

    projects = [_project_status(cfg, rel, revisions) for rel in wanted]

    if include_dirty_scan and not paths:
        # Any other manifest project that is dirty is worth surfacing, because a
        # sync would either refuse or clobber it.
        seen = {p.path for p in projects}
        for rel in revisions:
            if rel in seen:
                continue
            repo = cfg.tree.root / rel
            if not (repo / ".git").exists():
                continue
            porcelain = _git(repo, ["status", "--porcelain"], timeout=30)
            if porcelain.out.strip():
                projects.append(_project_status(cfg, rel, revisions))

    mismatches = [
        f"{p.path}: on {p.branch or '(detached)'}, manifest tracks {p.manifest_revision}"
        for p in projects
        if p.manifest_revision and not p.branch_matches_manifest
    ]
    return RepoStatus(
        projects=projects,
        dirty_count=sum(p.dirty_files for p in projects),
        mismatches=mismatches,
    )


# -- manifest_check ------------------------------------------------------


def manifest_check(cfg: Config) -> ManifestCheck:
    src = manifest_path(cfg)
    mirror = mirror_path(cfg)

    if not src.is_file():
        return ManifestCheck(
            mirror_identical=False,
            mirror_diff_summary=f"{src} does not exist",
            ok=False,
        )
    if not mirror.is_file():
        return ManifestCheck(
            mirror_identical=False,
            mirror_diff_summary=f"{mirror} does not exist - repo sync will not see the BestROM projects",
            ok=False,
        )

    identical = _sha256(src) == _sha256(mirror)
    summary = ""
    if not identical:
        diff = proc.run(["diff", "-u", str(mirror), str(src)], timeout=30)
        lines = [line for line in diff.out.splitlines() if line[:1] in {"+", "-"}]
        summary = "\n".join(lines[:40])

    try:
        root = ET.fromstring(src.read_text(encoding="utf-8", errors="replace"))
    except ET.ParseError as exc:
        return ManifestCheck(
            mirror_identical=identical,
            mirror_diff_summary=f"manifest does not parse: {exc}",
            ok=False,
        )

    copyfiles: list[CopyfileCheck] = []
    for project in root.findall("project"):
        if project.get("path") != "vendor/bestrom":
            continue
        for node in project.findall("copyfile"):
            rel_src = node.get("src", "")
            rel_dest = node.get("dest", "")
            source = cfg.tree.root / "vendor" / "bestrom" / rel_src
            dest = cfg.tree.root / rel_dest
            present = source.is_file()
            matches = present and dest.is_file() and _sha256(source) == _sha256(dest)
            detail = ""
            if not present:
                detail = f"source {source} missing"
            elif not dest.is_file():
                detail = f"root copy {dest} missing - run repo sync"
            elif not matches:
                detail = f"root copy {dest} differs from the source; a sync will overwrite it"
            copyfiles.append(
                CopyfileCheck(
                    src=rel_src, dest=rel_dest, present=present,
                    root_copy_matches=matches, detail=detail,
                )
            )

    forbidden = []
    for project in root.findall("project"):
        path = project.get("path", "")
        for bad in FORBIDDEN_PATHS:
            if path == bad or path.startswith(bad + "/"):
                forbidden.append(path)

    ok = identical and bool(copyfiles) and all(c.root_copy_matches for c in copyfiles) and not forbidden
    return ManifestCheck(
        mirror_identical=identical,
        mirror_diff_summary=summary,
        copyfiles=copyfiles,
        forbidden_paths_added=sorted(set(forbidden)),
        ok=ok,
    )


# -- repo_sync -----------------------------------------------------------


def validate_projects(projects: list[str]) -> tuple[list[str], str]:
    """Return (relative paths, refusal). Anything option-shaped is refused."""
    rels: list[str] = []
    for raw in projects:
        rel = str(raw).strip()
        if not rel:
            continue
        if rel.startswith("-"):
            return [], f"project {rel!r} looks like an option, not a path"
        if not PROJECT_RE.fullmatch(rel):
            return [], f"project {rel!r} is not a tree-relative path"
        if ".." in Path(rel).parts:
            return [], f"project {rel!r} contains a '..' segment"
        rels.append(rel)
    return rels, ""


def repo_sync(
    cfg: Config,
    projects: list[str] | None = None,
    jobs_count: int = 16,
    dry_run: bool = True,
    fetch: bool = False,
    confirm: bool = False,
    force_dirty: bool = False,
) -> SyncResult:
    jobs_count = max(1, min(int(jobs_count), 64))
    argv = ["repo", "sync", "-c", f"-j{jobs_count}", "--no-tags"]

    rels: list[str] = []
    if projects:
        rels, refusal = validate_projects(projects)
        if refusal:
            return SyncResult(dry_run=dry_run, refused_reason=refusal)
        for rel in rels:
            try:
                cfg.resolve_allowed(rel)  # must still land inside the tree
            except ValueError as exc:
                return SyncResult(dry_run=dry_run, refused_reason=str(exc))
        # "--" ends option parsing, so even a path repo would read as a flag
        # cannot become one.
        argv.extend(["--", *rels])
    preview = " ".join(shlex.quote(a) for a in argv)

    # The dirty guard always looks at the whole publish set. Scoping it to
    # `projects` would let a path that is not a checkout report a clean tree.
    status = repo_status(cfg, paths=None, include_dirty_scan=True)
    dirty = [p.path for p in status.projects if p.dirty_files]
    scoped = repo_status(cfg, paths=rels) if rels else status

    if dry_run:
        errors: list[str] = []
        if fetch:
            network = proc.run([*argv, "--network-only"], cwd=cfg.tree.root, timeout=1800)
            errors = network.err.splitlines()[-10:]
        return SyncResult(
            dry_run=True,
            fetched=fetch,
            would_sync=rels or [p.path for p in scoped.projects],
            command_preview=preview,
            errors_tail=errors,
            changed_projects=dirty,
            refused_reason=(
                f"dirty projects would block a real sync: {', '.join(dirty)}" if dirty else ""
            ),
        )

    if not confirm:
        return SyncResult(
            dry_run=False, command_preview=preview, changed_projects=dirty,
            refused_reason="confirm=true is required for a real sync",
        )
    if dirty and not force_dirty:
        return SyncResult(
            dry_run=False, command_preview=preview, changed_projects=dirty,
            refused_reason=(
                "refusing: uncommitted work in "
                + ", ".join(dirty)
                + " (pass force_dirty=true with confirm=true to sync anyway)"
            ),
        )

    result = proc.run(argv, cwd=cfg.tree.root, timeout=3600)
    return SyncResult(
        dry_run=False,
        started=True,
        fetched=True,
        exit_code=result.rc,
        command_preview=preview,
        changed_projects=[
            line.split()[-1] for line in result.out.splitlines() if line.startswith("project ")
        ][:50],
        errors_tail=result.err.splitlines()[-20:],
    )


# -- tree_repair ---------------------------------------------------------


def tree_repair(cfg: Config, dry_run: bool = True) -> RepairResult:
    """Recreate the seven build/make link results a partial sync loses."""
    root = cfg.tree.root
    missing: list[str] = []
    created: list[str] = []
    failed: list[str] = []
    present: list[str] = []

    for name in LINKFILES:
        target = root / "build" / name
        (present if target.exists() else missing).append(f"build/{name}")
    makefile = root / "Makefile"
    (present if makefile.exists() else missing).append("Makefile")

    if dry_run or not missing:
        return RepairResult(dry_run=dry_run, missing=missing, created=[], already_present=present)

    (root / "build").mkdir(parents=True, exist_ok=True)
    for name in LINKFILES:
        target = root / "build" / name
        if target.exists():
            continue
        try:
            target.symlink_to(Path("make") / name)
            created.append(f"build/{name}")
        except OSError as exc:
            failed.append(f"build/{name}: {exc}")
    if not makefile.exists():
        source = root / "build" / "make" / "core" / "root.mk"
        if source.is_file():
            try:
                makefile.write_bytes(source.read_bytes())
                created.append("Makefile")
            except OSError as exc:
                failed.append(f"Makefile: {exc}")
        else:
            failed.append("Makefile: build/make/core/root.mk missing")

    return RepairResult(
        dry_run=False, missing=missing, created=created, failed=failed,
        already_present=present,
    )
