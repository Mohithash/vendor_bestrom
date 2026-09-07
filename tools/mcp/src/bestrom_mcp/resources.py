"""bestrom:// resource bodies.

Resources answer the questions an agent would otherwise burn a tool call on,
and they are all bounded: the build log is tailed, never returned whole.
"""

from __future__ import annotations

import json

from . import proc
from .config import Config
from .ops import build as build_ops
from .ops import repo as repo_ops

STYLE_GUIDE = """# BestROM commit and changelog conventions

LineageOS style. The history is read by humans, and by the maintainer months
later trying to work out why a line changed.

## Subject

    area: Sentence-case summary

* `area` is a real path prefix in the tree: `vendor`, `device/xiaomi/peridot`,
  `frameworks/base`, `packages/apps/Settings`, `sepolicy`, `docs`.
* 50 characters reads best in `git log --oneline`; 72 is the hard limit.
* No trailing period. Imperative or simple present, not past tense.

## Body

* Blank second line, always.
* 1 to 6 lines, each wrapped at 72 characters.
* Say what changed and why. The diff already says how.
* Plain English. None of: comprehensive, robust, seamless, leverage, delve,
  cutting-edge, streamline, meticulous, "enhance the experience".
* No emoji anywhere.

## Trailers

Only `Signed-off-by:`, `Change-Id:`, `Fixes:`, `Reverts:` and `Bug:`. The ROM
repositories carry no AI attribution: no `Co-Authored-By: Claude`, no
"Generated with [Claude Code]", no robot emoji.

## Publish-chain subjects

Two subjects are written by the publish chain and are deliberately not in the
`area: Summary` form. Do not "fix" them:

    17: 3.0-peridot-20260907-1010-OFFICIAL
    docs: latest release card (3.0-peridot-20260907-1010-OFFICIAL)

## Changelog

`vendor/bestrom/CHANGELOG.md` opens with `Unreleased (next build)`. Entries are
a section heading in plain text followed by two-space `  * ` bullets wrapped at
72 characters. Release sections repeat the SourceForge README header verbatim,
so the two never drift.

## Examples

    vendor: Add the BestROM MCP server

    Wraps the build, verify, device and release chains as MCP tools so an
    agent can drive them without ad-hoc shell. Read-only by default; the
    mutating tools take dry_run and a separate confirm.

    sepolicy: Drop the CAP_SYS_ADMIN grant to fsck_untrusted

    AOSP neverallows this and calls the grant a code mistake, so stock and
    every other peridot ROM deny it. We were the odd one out and detection
    tools flagged the live policy as dirty.
"""


def manifest_resource(cfg: Config) -> str:
    src = repo_ops.manifest_path(cfg)
    check = repo_ops.manifest_check(cfg)
    header = (
        "<!-- vendor/bestrom/manifest/bestrom.xml\n"
        f"     mirror .repo/local_manifests/bestrom.xml byte-identical right now: "
        f"{check.mirror_identical}\n"
        "     Do not add hardware/qcom-caf/*, vendor/qcom/opensource/*,\n"
        "     device/qcom/sepolicy_vndr/sm8650, hardware/xiaomi,\n"
        "     hardware/google/pixel or hardware/nxp/* - VoltageOS's manifest has\n"
        "     them and repo rejects duplicate paths. -->\n"
    )
    if not src.is_file():
        return header + f"<!-- {src} does not exist -->\n"
    try:
        return header + src.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return header + f"<!-- unreadable: {exc} -->\n"


def changelog_resource(cfg: Config) -> str:
    path = cfg.tree.root / "vendor" / "bestrom" / "CHANGELOG.md"
    if not path.is_file():
        return f"(no changelog at {path})\n"
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(unreadable: {exc})\n"


def latest_log_resource(cfg: Config) -> str:
    log = build_ops.newest_log(cfg)
    if log is None:
        return f"(no {cfg.build.log_prefix}*.log in {cfg.tree.logs_dir})\n"
    tail = proc.tail_file(log, lines=400)
    errors = build_ops.build_errors(cfg, log_path=str(log), limit=12)
    head = [
        f"log: {log}",
        f"BUILD EXIT: {errors.build_exit if errors.build_exit is not None else '(not finished)'}",
        f"FAILED targets: {len(errors.failed_targets)}  error lines: {len(errors.errors)}",
        "",
    ]
    if errors.failed_targets or errors.errors:
        head.append("-- extract --")
        head.extend(errors.failed_targets)
        head.extend(errors.errors)
        head.append("")
    head.append("-- last 400 lines --")
    return "\n".join([*head, *tail]) + "\n"


def style_guide_resource(_cfg: Config) -> str:
    return STYLE_GUIDE


def device_evidence_resource(cfg: Config) -> str:
    root = cfg.device.evidence_dir
    if not root.is_dir():
        return f"(no evidence directory at {root})\n"
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if not dirs:
        return f"(no captures under {root})\n"
    newest = max(dirs, key=lambda p: p.stat().st_mtime)

    lines = [f"# Latest capture: {newest}", ""]
    for name in ("index.txt", "device.txt"):
        path = newest / name
        if path.is_file():
            lines.append(f"## {name}")
            lines.append("```")
            lines.extend(proc.tail_file(path, lines=60))
            lines.append("```")
            lines.append("")
    for name, title in (
        ("crash-summary.txt", "process :: first exception line"),
        ("avc-other.txt", "avc denials"),
        ("avc.txt", "avc denials"),
    ):
        path = newest / name
        if path.is_file():
            lines.append(f"## {title} ({name})")
            lines.append("```")
            lines.extend(proc.tail_file(path, lines=40))
            lines.append("```")
            lines.append("")

    lines.append("## files")
    lines.append("")
    lines.append("| File | Size |")
    lines.append("|---|---|")
    for path in sorted(newest.iterdir()):
        if path.is_file():
            lines.append(f"| `{path.name}` | {path.stat().st_size} |")
    return "\n".join(lines) + "\n"


def config_resource(cfg: Config) -> str:
    from .redact import scrub_any

    return json.dumps(scrub_any(cfg.redacted_dict()), indent=2) + "\n"
