"""Typed tool results.

Every tool returns one of these. MCPServer derives ``outputSchema`` from the
return annotation, so the client sees ``structuredContent`` rather than a wall
of text it has to parse.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CcacheStats(BaseModel):
    hit_rate: str = ""
    cacheable: str = ""


class BuildInFlight(BaseModel):
    running: bool = False
    unit: str = ""
    log: str = ""


class EnvReport(BaseModel):
    tree: str
    ok: bool
    cores: int
    mem_available_gb: int
    disk_free_gb: int
    out_size_gb: float
    headroom_ok: bool
    ccache: CcacheStats
    repo_version: str
    envsetup_present: bool
    makefile_present: bool
    lunch_target_available: bool
    systemd_user_ok: bool
    build_in_flight: BuildInFlight
    adb_port_listener: bool
    blockers: list[str] = Field(default_factory=list)


class ProjectStatus(BaseModel):
    path: str
    branch: str = ""
    manifest_revision: str = ""
    branch_matches_manifest: bool = False
    dirty_files: int = 0
    ahead: int = 0
    behind: int = 0
    head_short: str = ""
    error: str = ""


class RepoStatus(BaseModel):
    projects: list[ProjectStatus] = Field(default_factory=list)
    dirty_count: int = 0
    mismatches: list[str] = Field(default_factory=list)


class CopyfileCheck(BaseModel):
    src: str
    dest: str
    present: bool
    root_copy_matches: bool
    detail: str = ""


class ManifestCheck(BaseModel):
    mirror_identical: bool
    mirror_diff_summary: str = ""
    copyfiles: list[CopyfileCheck] = Field(default_factory=list)
    forbidden_paths_added: list[str] = Field(default_factory=list)
    ok: bool = False


class SyncResult(BaseModel):
    dry_run: bool
    fetched: bool = False
    would_sync: list[str] = Field(default_factory=list)
    started: bool = False
    exit_code: int | None = None
    changed_projects: list[str] = Field(default_factory=list)
    errors_tail: list[str] = Field(default_factory=list)
    command_preview: str = ""
    refused_reason: str = ""


class RepairResult(BaseModel):
    dry_run: bool
    missing: list[str] = Field(default_factory=list)
    created: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    already_present: list[str] = Field(default_factory=list)


class BuildJob(BaseModel):
    dry_run: bool
    command_preview: str = ""
    job_id: str = ""
    official: bool = True
    note: str = ""
    log_path: str = ""
    started_at_utc: str = ""
    refused_reason: str = ""


class BuildStatus(BaseModel):
    job_id: str = ""
    unit_state: str = ""
    sub_state: str = ""
    exit_status: int | None = None
    elapsed_s: int = 0
    build_exit: int | None = None
    finished: bool = False
    log_path: str = ""
    log_tail: list[str] = Field(default_factory=list)
    note: str = ""


class BuildErrors(BaseModel):
    log_path: str = ""
    build_exit: int | None = None
    failed_targets: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    truncated: bool = False


class CancelResult(BaseModel):
    job_id: str
    stopped: bool = False
    unit_state: str = ""
    refused_reason: str = ""


class ZipInfo(BaseModel):
    name: str = ""
    path: str = ""
    size: int = 0
    size_gb: float = 0.0
    mtime: str = ""
    sha256: str = ""


class ImageFile(BaseModel):
    name: str
    size: int


class PreviousRelease(BaseModel):
    name: str = ""
    size: int = 0
    delta_mb: int = 0


class Artifacts(BaseModel):
    zip: ZipInfo = Field(default_factory=ZipInfo)
    sidecar_sha256_present: bool = False
    generic_ota_zip: str = ""
    images: list[ImageFile] = Field(default_factory=list)
    build_props: dict[str, str] = Field(default_factory=dict)
    previous_release: PreviousRelease = Field(default_factory=PreviousRelease)
    note: str = ""


class CheckResult(BaseModel):
    id: str
    kind: str
    description: str = ""
    expected: str = ""
    op: str = ""
    actual: str = ""
    passed: bool = False
    forbidden: bool = False
    detail: str = ""


class VerifyReport(BaseModel):
    profile: str
    checks: list[CheckResult] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    partial: bool = False
    passed: bool = False
    failed_ids: list[str] = Field(default_factory=list)
    zip: ZipInfo = Field(default_factory=ZipInfo)
    delta_mb: int = 0
    marker_path: str = ""
    marker_line: str = ""
    note: str = ""


class DeviceEntry(BaseModel):
    serial: str
    state: str
    is_configured_serial: bool = False


class DeviceList(BaseModel):
    port: int
    listener_present: bool
    listener_owner: str = ""
    devices: list[DeviceEntry] = Field(default_factory=list)
    props: dict[str, str] = Field(default_factory=dict)
    selinux: str = ""
    root_via_su: bool = False
    uptime: str = ""
    unreachable_reason: str = ""


class CaptureSummary(BaseModel):
    tag_histogram: list[str] = Field(default_factory=list)
    crash_summary: list[str] = Field(default_factory=list)
    fatal_count: int = 0
    avc_histogram: list[str] = Field(default_factory=list)
    package_counts: dict[str, int] = Field(default_factory=dict)
    root_used: bool = False
    truncated: bool = False


class CaptureResult(BaseModel):
    kind: str
    out_dir: str = ""
    files: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    summary: CaptureSummary = Field(default_factory=CaptureSummary)
    refused_reason: str = ""


class SideloadPlan(BaseModel):
    dry_run: bool
    refused_reason: str = ""
    local_commands: list[str] = Field(default_factory=list)
    zip: ZipInfo = Field(default_factory=ZipInfo)
    device_state: str = ""
    paired_images_ok: bool = True


class ReleaseGate(BaseModel):
    verify_marker_ok: bool = False
    zip_matches_marker: bool = False
    marker_path: str = ""
    detail: str = ""


class ReleaseDrafts(BaseModel):
    version: str = ""
    zip: ZipInfo = Field(default_factory=ZipInfo)
    readme_txt: str = ""
    changelog_entry: str = ""
    ota_json: str = ""
    site_card_diff: list[str] = Field(default_factory=list)
    written_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    gate: ReleaseGate = Field(default_factory=ReleaseGate)
    dry_run: bool = True
    refused_reason: str = ""


class StageResult(BaseModel):
    stage: str
    status: str
    detail: str = ""
    log_path: str = ""


class PublishResult(BaseModel):
    dry_run: bool
    gates: ReleaseGate = Field(default_factory=ReleaseGate)
    planned_stages: list[str] = Field(default_factory=list)
    stage_results: list[StageResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    command_preview: str = ""
    refused_reason: str = ""


class ChangelogResult(BaseModel):
    dry_run: bool
    diff: str = ""
    path: str = ""
    wrapped_at_72: bool = True
    refused_reason: str = ""


class StyleViolation(BaseModel):
    rule_id: str
    severity: str
    line: int
    message: str
    suggestion: str = ""


class StyleReport(BaseModel):
    ok: bool
    subject: str = ""
    area: str = ""
    violations: list[StyleViolation] = Field(default_factory=list)
    suggested_message: str = ""


class TrailerCommit(BaseModel):
    sha: str
    subject: str
    offending_lines: list[str] = Field(default_factory=list)


class TrailerScan(BaseModel):
    repo: str
    range: str = ""
    commits: list[TrailerCommit] = Field(default_factory=list)
    count: int = 0
    rewrite_command: str = ""
    note: str = ""
