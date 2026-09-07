"""The BestROM MCP server.

Tools, resources and prompts are registered in one fixed order so ``tools/list``
is deterministic across runs — a client that caches the list, and a smoke test
that asserts on it, both depend on that.

There is deliberately no ``run_shell`` and no ``execute_adb_command``: that
escape hatch would defeat every gate in this file.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, prompts, resources
from .config import Config, PathNotAllowed, load_config
from .ops.verify import ProfileError, load_profile
from .models import (
    Artifacts,
    BuildErrors,
    BuildJob,
    BuildStatus,
    CancelResult,
    CaptureResult,
    ChangelogResult,
    DeviceList,
    EnvReport,
    ManifestCheck,
    PublishResult,
    ReleaseDrafts,
    RepairResult,
    RepoStatus,
    SideloadPlan,
    StyleReport,
    SyncResult,
    TrailerScan,
    VerifyReport,
)
from .ops import build as build_ops
from .ops import device as device_ops
from .ops import env as env_ops
from .ops import release as release_ops
from .ops import repo as repo_ops
from .ops import style as style_ops
from .ops import verify as verify_ops

log = logging.getLogger("bestrom_mcp")

INSTRUCTIONS = """Tools for the BestROM Android 17 tree (POCO F6, peridot).

Start with env_check. Build with build_start (dry_run first) and poll with
build_status; a build takes hours and runs detached, so never hold a call open
waiting for it. Gate every image with verify_image before release_prepare, and
never push: release_publish is the only tool that pushes, and it re-checks both
anti-drift gates and requires confirm=true.

On the phone: adb only ever runs on port 15038 and only when ss shows a
listener, because adb -P against an unbound port steals the tunnel port. It is a
user build with no root, so empty tombstone output is not evidence of no
crashes.

Every mutating tool defaults to dry_run=true and returns the exact command it
would run.
"""


def _ann(
    title: str,
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> ToolAnnotations:
    """Annotations are hints for the client UI. The real gates are in code."""
    return ToolAnnotations(
        title=title,
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


# ``from __future__ import annotations`` is on in this module, so a tool's
# Annotated[...] metadata is a string the MCP server evaluates later against
# these module globals. A closure variable of build_server() is not visible
# there - the server refuses to start with a NameError - so the schema pieces
# that depend on the configuration live here and are filled in at the top of
# build_server(), before any tool is registered.
CHAIN_FIELD: Any = Field(description="Chain slug")
CHECKS_FIELD: Any = Field(default=None, description="Run only these check ids")


def _profile_check_ids(cfg: Config) -> list[str]:
    """The check ids of the configured profile, for the tool schema.

    They are known at registration time, so an agent should not have to learn
    them from a refusal.
    """
    try:
        profile = load_profile(cfg.profiles_path / f"{cfg.verify.profile}.toml")
    except (ProfileError, OSError):
        return []
    return [str(c.get("id")) for c in profile.get("check", []) if c.get("id")]


def build_server(cfg: Config | None = None) -> MCPServer:
    global CHAIN_FIELD, CHECKS_FIELD

    cfg = cfg or load_config()
    check_ids = _profile_check_ids(cfg)

    CHAIN_FIELD = Field(
        description="Chain slug: " + ", ".join(cfg.release.chains),
        json_schema_extra={"enum": list(cfg.release.chains)},
    )
    CHECKS_FIELD = Field(
        default=None,
        description=(
            "Run only these check ids. A subset is a diagnostic and can never "
            "write the marker."
            + (" Valid ids: " + ", ".join(check_ids) if check_ids else "")
        ),
    )

    server = MCPServer(
        name="bestrom",
        title="BestROM",
        version=__version__,
        instructions=INSTRUCTIONS,
    )

    # -- environment ----------------------------------------------------

    @server.tool(
        name="env_check",
        title="Check the build environment",
        annotations=_ann("Check the build environment", read_only=True, idempotent=True),
    )
    def env_check() -> EnvReport:
        """Preflight the tree before anything expensive.

        Reports cores, free memory, free disk against the required headroom,
        out/ size, ccache, whether build/envsetup.sh and ./Makefile exist,
        whether bestrom_peridot is a lunch target, whether systemd --user can
        run a detached job, whether a build is already in flight, and whether
        the adb tunnel port has a listener. Blockers are listed explicitly.
        """
        return env_ops.env_check(cfg)

    # -- tree -----------------------------------------------------------

    @server.tool(
        name="repo_status",
        title="Repo and branch status",
        annotations=_ann("Repo and branch status", read_only=True, idempotent=True),
    )
    def repo_status(
        paths: Annotated[
            list[str] | None,
            Field(default=None, description="Project paths; defaults to the publish set plus vendor/bestrom"),
        ] = None,
        include_dirty_scan: Annotated[
            bool, Field(default=True, description="Also report any other manifest project that is dirty")
        ] = True,
    ) -> RepoStatus:
        """Is the tree safe to build, and does anything need committing?

        Per project: current branch against the manifest revision, dirty file
        count, ahead/behind. Branch-versus-manifest mismatches are listed
        separately, because committing to the wrong branch means the change
        never reaches a build.
        """
        return repo_ops.repo_status(cfg, paths=paths, include_dirty_scan=include_dirty_scan)

    @server.tool(
        name="manifest_check",
        title="Check the manifest mirror and copyfiles",
        annotations=_ann("Check the manifest mirror and copyfiles", read_only=True, idempotent=True),
    )
    def manifest_check() -> ManifestCheck:
        """Enforce the reproducibility rule for root-level files.

        vendor/bestrom/manifest/bestrom.xml and .repo/local_manifests/bestrom.xml
        must be byte-identical, the <copyfile> entries must be present, and each
        root copy must still match its source under vendor/bestrom/tools/ — a
        root file edited in place is silently lost on the next sync. Also warns
        if a project path VoltageOS already provides was added.
        """
        return repo_ops.manifest_check(cfg)

    @server.tool(
        name="repo_sync",
        title="Sync the tree from the manifest",
        annotations=_ann("Sync the tree from the manifest", destructive=True, open_world=True),
    )
    def repo_sync(
        projects: Annotated[
            list[str] | None,
            Field(default=None, description="Tree-relative project paths; default all"),
        ] = None,
        jobs: Annotated[int, Field(default=16, ge=1, le=64, description="Parallel fetches")] = 16,
        dry_run: Annotated[bool, Field(default=True, description="Report only; write nothing")] = True,
        fetch: Annotated[
            bool,
            Field(default=False, description="On a dry run, also run repo sync --network-only (network, slow)"),
        ] = False,
        confirm: Annotated[bool, Field(default=False, description="Required for a real sync")] = False,
        force_dirty: Annotated[bool, Field(default=False, description="Sync even with uncommitted work")] = False,
    ) -> SyncResult:
        """Drive repo sync without letting uncommitted work be clobbered.

        A dry run is local by default - manifest revisions against current
        branches, dirty projects, the command preview - because a
        --network-only fetch of an AOSP tree is tens of gigabytes; pass
        fetch=true when you want it. A real sync needs confirm=true and refuses
        while any project in the publish set is dirty unless force_dirty is
        also set. --force-sync is never passed, and each entry of `projects`
        must be a tree-relative path: anything starting with '-' is refused
        and the paths go after a literal '--'.
        """
        return repo_ops.repo_sync(
            cfg, projects=projects, jobs_count=jobs, dry_run=dry_run, fetch=fetch,
            confirm=confirm, force_dirty=force_dirty,
        )

    @server.tool(
        name="tree_repair",
        title="Recreate the build/ link results",
        annotations=_ann("Recreate the build/ link results", idempotent=True),
    )
    def tree_repair(
        dry_run: Annotated[bool, Field(default=True, description="Report what is missing without writing")] = True,
    ) -> RepairResult:
        """Restore the seven build/make link results a partial sync loses.

        build/{CleanSpec.mk,buildspec.mk.default,core,envsetup.sh,target,tools}
        are <linkfile> results and ./Makefile is a <copyfile> of
        build/make/core/root.mk. Without them the tree has no envsetup at all.
        Writes only those seven paths and never deletes anything.
        """
        return repo_ops.tree_repair(cfg, dry_run=dry_run)

    # -- build ----------------------------------------------------------

    @server.tool(
        name="build_start",
        title="Start a detached build",
        annotations=_ann("Start a detached build"),
    )
    def build_start(
        target: Annotated[
            Literal["bestrom", "installclean", "otapackage"],
            Field(default="bestrom", description="Make goal"),
        ] = "bestrom",
        installclean: Annotated[
            bool, Field(default=False, description="Run m installclean first; required when the product config changed")
        ] = False,
        jobs: Annotated[int | None, Field(default=None, ge=1, le=256, description="Parallel jobs")] = None,
        log_name: Annotated[str, Field(default="mcp", description="Slug for the log filename")] = "mcp",
        dry_run: Annotated[bool, Field(default=True, description="Return the command and log path without launching")] = True,
    ) -> BuildJob:
        """Launch the canonical build as a transient systemd --user unit.

        Wraps build-bestrom-run.sh rather than reimplementing lunch and mka,
        because envsetup exports shell functions and a bare mka leaks
        eng.<user> into ro.build.fingerprint. The job survives this server
        exiting; poll it with build_status. Refuses — never queues — while
        soong_ui or ninja is running, and names the log that build is writing.

        There is no official flag: build-bestrom-run.sh exports
        BESTROM_OFFICIAL itself, so every build through this tool carries the
        stamp that script sets. The result says which, and why.
        """
        return build_ops.build_start(
            cfg, target=target, installclean=installclean,
            jobs_count=jobs, log_name=log_name, dry_run=dry_run,
        )

    @server.tool(
        name="build_status",
        title="Poll a build",
        annotations=_ann("Poll a build", read_only=True),
    )
    def build_status(
        job_id: Annotated[str, Field(default="", description="Defaults to the newest job")] = "",
        tail_lines: Annotated[int, Field(default=40, ge=1, le=200, description="Log lines to return")] = 40,
    ) -> BuildStatus:
        """Unit state plus the parsed 'BUILD EXIT: N' line and a bounded tail.

        Reads the systemd unit and the log file rather than an in-process
        handle, so it still works after the server restarts. The tail is capped
        at 200 lines because a build log reaches 21 MB.
        """
        return build_ops.build_status(cfg, job_id=job_id, tail_lines=tail_lines)

    @server.tool(
        name="build_errors",
        title="Extract build failures",
        annotations=_ann("Extract build failures", read_only=True, idempotent=True),
    )
    def build_errors(
        job_id: Annotated[str, Field(default="", description="Defaults to the newest job")] = "",
        log_path: Annotated[str, Field(default="", description="Explicit log file, inside the allowlist")] = "",
        limit: Annotated[int, Field(default=12, ge=1, le=50, description="Maximum lines of each kind")] = 12,
    ) -> BuildErrors:
        """Turn a failed build into something actionable without reading 21 MB.

        Streams the log for FAILED: and error: lines, drops warnings,
        deduplicates, and truncates each line.
        """
        return build_ops.build_errors(cfg, job_id=job_id, log_path=log_path, limit=limit)

    @server.tool(
        name="build_cancel",
        title="Stop a running build",
        annotations=_ann("Stop a running build", destructive=True),
    )
    def build_cancel(
        job_id: Annotated[str, Field(description="Job id from build_start")],
        confirm: Annotated[bool, Field(default=False, description="Required to stop the build")] = False,
    ) -> CancelResult:
        """Stop a build by unit name, never by matching a process command line.

        Only a unit this server started, recorded in the job registry and
        carrying the configured prefix, can be stopped.
        """
        return build_ops.build_cancel(cfg, job_id=job_id, confirm=confirm)

    @server.tool(
        name="build_artifacts",
        title="Describe the built package",
        annotations=_ann("Describe the built package", read_only=True, idempotent=True),
    )
    def build_artifacts(
        compute_sha256: Annotated[
            bool, Field(default=False, description="Hash the 2.7 GB package (~10 s) if no sidecar exists")
        ] = False,
        include_images: Annotated[bool, Field(default=True, description="List boot/vendor_boot/etc")] = True,
    ) -> Artifacts:
        """Locate the package and read its real identity out of build.prop.

        Uses the naming contract from config/branding.mk
        (BestROM-<ver>-peridot-<date>-<time>-<OFFICIAL|UNOFFICIAL>.zip) rather
        than guessing, reads the existing .sha256 sidecar first, and reports the
        size delta against the previous package.
        """
        return build_ops.build_artifacts(
            cfg, compute_sha256=compute_sha256, include_images=include_images
        )

    # -- verify ---------------------------------------------------------

    @server.tool(
        name="verify_image",
        title="Run the image gate",
        annotations=_ann("Run the image gate", read_only=True, idempotent=True),
    )
    def verify_image(
        profile: Annotated[str, Field(default="", description="Profile name; defaults to the configured one")] = "",
        checks: Annotated[list[str] | None, CHECKS_FIELD] = None,
        write_marker: Annotated[
            bool, Field(default=False, description="Write the build marker the publish gate reads")
        ] = False,
        marker_name: Annotated[
            str,
            Field(default="", description="Marker filename; must be chain-<slug>-build.done"),
        ] = "",
    ) -> VerifyReport:
        """The project's quality gate, as a declarative profile.

        Keeps the expected/forbidden symmetry: a gate that only checks that the
        wanted thing is present passes a broken image. write_marker is the one
        write and it only ever touches a chain marker file. It writes the
        literal 'verify gate passed' only after the whole profile ran clean:
        passing a subset in `checks` is a diagnostic and is refused a marker,
        and the marker records how many checks ran so the publish gate can
        reject a partial one.
        """
        return verify_ops.verify_image(
            cfg, profile_name=profile, checks=checks,
            write_marker=write_marker, marker_name=marker_name,
        )

    # -- device ---------------------------------------------------------

    @server.tool(
        name="device_list",
        title="Check the phone over the tunnel",
        annotations=_ann("Check the phone over the tunnel", read_only=True, open_world=True),
    )
    def device_list() -> DeviceList:
        """Report device reachability without tripping the adb port trap.

        Checks `ss -ltn` for a listener on the tunnel port first and refuses to
        run adb at all when there is none: adb -P on an unbound port spawns a
        daemon that squats the port and the tunnel can then never bind. Also
        probes root, because on this user build an empty tombstone dump reads to
        an agent as 'no crashes'.
        """
        try:
            return device_ops.device_list(cfg)
        except device_ops.PortUnbound as exc:
            return DeviceList(
                port=cfg.device.adb_port, listener_present=False, unreachable_reason=str(exc)
            )

    @server.tool(
        name="device_capture",
        title="Capture device evidence",
        annotations=_ann("Capture device evidence", open_world=True),
    )
    def device_capture(
        kind: Annotated[
            Literal["crashes", "logcat", "dropbox", "screenshot", "avc", "packages"],
            Field(description="What to capture"),
        ],
        package: Annotated[str, Field(default="", description="Restrict to one installed package")] = "",
        timeout_s: Annotated[int, Field(default=60, ge=10, le=300, description="Per-command timeout")] = 60,
        out_dir: Annotated[str, Field(default="", description="Directory under the evidence root")] = "",
    ) -> CaptureResult:
        """Structured evidence capture into a timestamped directory.

        Returns a small summary — tag histogram, 'process :: first exception
        line' rollup, avc histogram, file list — and leaves the bulk on disk
        behind bestrom://device-evidence/latest. Root-gated commands say so when
        root was unavailable. There is no arbitrary shell here: package is
        validated against pm list packages.
        """
        try:
            return device_ops.device_capture(
                cfg, kind=kind, package=package, timeout_s=timeout_s, out_dir=out_dir
            )
        except (device_ops.PortUnbound, PathNotAllowed, OSError) as exc:
            return CaptureResult(kind=kind, refused_reason=str(exc))

    @server.tool(
        name="device_sideload",
        title="Plan a flash",
        annotations=_ann("Plan a flash", destructive=True, open_world=True),
    )
    def device_sideload(
        zip_path: Annotated[str, Field(default="", description="Package to flash; defaults to the newest")] = "",
        images: Annotated[list[str] | None, Field(default=None, description="boot and/or vendor_boot")] = None,
        confirm: Annotated[bool, Field(default=False, description="Required to actually flash")] = False,
        dry_run: Annotated[bool, Field(default=True, description="Return the plan only")] = True,
        allow_remote: Annotated[bool, Field(default=False, description="Attempt it over the tunnel anyway")] = False,
    ) -> SideloadPlan:
        """Deliberately does not flash over the tunnel.

        A 2.7 GB package over the reverse tunnel runs at ~0.7 MB/s and drops
        before it finishes, leaving the phone in recovery with a half-written
        update — so this refuses and returns the exact local command instead. It
        also refuses a boot.img flash that does not include vendor_boot.img,
        which is how the QRTR sensor bootloop was reproduced, and refuses any
        package the verify gate has not passed.
        """
        return device_ops.device_sideload(
            cfg, zip_path=zip_path, images=images, confirm=confirm,
            dry_run=dry_run, allow_remote=allow_remote,
        )

    # -- release --------------------------------------------------------

    @server.tool(
        name="release_prepare",
        title="Draft the release documents",
        annotations=_ann("Draft the release documents"),
    )
    def release_prepare(
        notes: Annotated[str, Field(default="", description="Release notes, in the changelog's voice")] = "",
        notes_path: Annotated[str, Field(default="", description="Read the notes from a file instead")] = "",
        previous: Annotated[str, Field(default="", description="Previous package name; default from the OTA catalog")] = "",
        dry_run: Annotated[bool, Field(default=True, description="Return drafts without writing them")] = True,
    ) -> ReleaseDrafts:
        """Assemble the SourceForge README, the changelog entry and the OTA
        catalog from one set of notes, and render the site card as a diff.

        Publishes nothing. dry_run=false writes drafts under the release staging
        directory and still pushes and uploads nothing.
        """
        return release_ops.release_prepare(
            cfg, notes=notes, notes_path=notes_path, previous=previous, dry_run=dry_run
        )

    @server.tool(
        name="release_publish",
        title="Run the publish chain",
        annotations=_ann("Run the publish chain", destructive=True, open_world=True),
    )
    def release_publish(
        chain: Annotated[str, CHAIN_FIELD],
        confirm: Annotated[bool, Field(default=False, description="Required to publish")] = False,
        dry_run: Annotated[bool, Field(default=True, description="Report the plan and the gates only")] = True,
    ) -> PublishResult:
        """Run chain-<chain>-publish.sh: 7 repo pushes, a SourceForge upload, an
        htdocs overwrite and the OTA catalog every user's Updater reads.

        There is no stage selection. The chain scripts take no arguments and
        run all four stages, so this tool does not offer a subset it could not
        enforce. Both anti-drift gates are re-evaluated here and never trusted
        from an earlier call: the build marker must contain the literal 'verify
        gate passed' for a full profile run, and the newest package on disk
        must be the filename the marker recorded. It also refuses when the
        chain script's PREVZ still names an older package, because its site
        card and OTA commit body would then be the previous release's.
        """
        return release_ops.release_publish(
            cfg, chain=chain, confirm=confirm, dry_run=dry_run
        )

    @server.tool(
        name="changelog_add",
        title="Add a changelog section",
        annotations=_ann("Add a changelog section"),
    )
    def changelog_add(
        section: Annotated[str, Field(description="Section heading, e.g. Camera")],
        bullets: Annotated[list[str], Field(description="One entry per bullet; wrapped at 72")],
        dry_run: Annotated[bool, Field(default=True, description="Return the diff without writing")] = True,
    ) -> ChangelogResult:
        """Append a section under 'Unreleased (next build)' in
        vendor/bestrom/CHANGELOG.md, in the existing two-space bullet style.

        Touches exactly one file and never commits or pushes.
        """
        return release_ops.changelog_add(cfg, section=section, bullets=bullets, dry_run=dry_run)

    # -- style ----------------------------------------------------------

    @server.tool(
        name="commit_message_check",
        title="Check a commit message",
        annotations=_ann("Check a commit message", read_only=True, idempotent=True),
    )
    def commit_message_check(
        text: Annotated[str, Field(description="The full commit message")],
        strict: Annotated[bool, Field(default=False, description="Promote warnings to errors")] = False,
    ) -> StyleReport:
        """The BestROM commit style as a checkable function.

        Subject 'area: Sentence-case summary' with a real path prefix, 50/72, no
        trailing period, blank second line, 1-6 body lines wrapped at 72, no
        emoji, no AI vocabulary, no unapproved trailers. Returns the rule id and
        severity of each violation plus a mechanically repaired message.
        """
        return style_ops.commit_message_check(text, strict=strict)

    @server.tool(
        name="strip_ai_trailers",
        title="Find AI attribution in history",
        annotations=_ann("Find AI attribution in history", read_only=True, idempotent=True),
    )
    def strip_ai_trailers(
        repo: Annotated[str, Field(description="Project path inside the tree")],
        since: Annotated[
            str,
            Field(default="", description="Range; default <remote>/<manifest revision>..HEAD"),
        ] = "",
    ) -> TrailerScan:
        """Report which commits carry AI attribution, and hand back the rewrite
        command for the maintainer to run.

        It never rewrites history: rewrites in a repo-managed tree are the
        maintainer's to run deliberately, not something that happens behind an
        agent call. The command it returns needs git-filter-repo installed.
        """
        return style_ops.strip_ai_trailers(cfg, repo=repo, since=since)

    # -- resources ------------------------------------------------------

    @server.resource(
        "bestrom://manifest",
        name="BestROM manifest",
        description="vendor/bestrom/manifest/bestrom.xml, with a header saying whether the .repo mirror is identical right now.",
        mime_type="text/xml",
    )
    def manifest_resource() -> str:
        return resources.manifest_resource(cfg)

    @server.resource(
        "bestrom://changelog",
        name="BestROM changelog",
        description="vendor/bestrom/CHANGELOG.md — the voice and section structure release notes must match.",
        mime_type="text/markdown",
    )
    def changelog_resource() -> str:
        return resources.changelog_resource(cfg)

    @server.resource(
        "bestrom://build/latest-log",
        name="Latest build log",
        description="Last 400 lines of the newest build log, the parsed BUILD EXIT line and any FAILED:/error: extract. Never the whole file.",
        mime_type="text/plain",
    )
    def latest_log_resource() -> str:
        return resources.latest_log_resource(cfg)

    @server.resource(
        "bestrom://style-guide",
        name="Commit and changelog style",
        description="The conventions commit_message_check enforces, in prose, so they can be read before writing rather than after failing.",
        mime_type="text/markdown",
    )
    def style_guide_resource() -> str:
        return resources.style_guide_resource(cfg)

    @server.resource(
        "bestrom://device-evidence/latest",
        name="Latest device evidence",
        description="Index of the newest crash-sweep capture: summary, crash rollup, avc histogram and the file list with sizes.",
        mime_type="text/markdown",
    )
    def device_evidence_resource() -> str:
        return resources.device_evidence_resource(cfg)

    @server.resource(
        "bestrom://config",
        name="Effective configuration",
        description="The configuration after TOML plus environment overrides, redacted — including which destructive operations are enabled and why a tool may have refused.",
        mime_type="application/json",
    )
    def config_resource() -> str:
        return resources.config_resource(cfg)

    # -- prompts --------------------------------------------------------

    @server.prompt(name="release-checklist", title="Release a build")
    def release_checklist() -> str:
        """The full release in the project's order, with both anti-drift gates."""
        return prompts.RELEASE_CHECKLIST

    @server.prompt(name="crash-triage", title="Triage a phone-side crash")
    def crash_triage() -> str:
        """Turn a report into evidence before proposing a change."""
        return prompts.CRASH_TRIAGE

    @server.prompt(name="new-feature-branch", title="Start a change")
    def new_feature_branch() -> str:
        """Branch, change, check the message, changelog, and stop before pushing."""
        return prompts.NEW_FEATURE_BRANCH

    @server.prompt(name="build-triage", title="Diagnose a failed build")
    def build_triage() -> str:
        """Read the exit line and the error extract, then decide the clean level."""
        return prompts.BUILD_TRIAGE

    return server
