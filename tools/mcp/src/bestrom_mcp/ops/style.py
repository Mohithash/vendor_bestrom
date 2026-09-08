"""commit_message_check and strip_ai_trailers.

The BestROM history is read by humans, so the commit conventions are a
checkable function rather than a paragraph in a README. ``commit_message_check``
is pure: no subprocess, no filesystem.

``strip_ai_trailers`` only ever reports. Rewriting history in a repo-managed
tree is the maintainer's job, so the tool hands back the command instead of
running it.
"""

from __future__ import annotations

import re
import shlex
import textwrap
from pathlib import Path

from .. import proc
from ..config import Config
from ..models import StyleReport, StyleViolation, TrailerCommit, TrailerScan

SUBJECT_SOFT_LIMIT = 50
SUBJECT_HARD_LIMIT = 72
BODY_LIMIT = 72
BODY_MAX_LINES = 6

# Area prefixes that map to a real path in the tree, plus the two subjects the
# publish chain writes into the OTA and site repos.
KNOWN_AREAS = {
    "art", "bionic", "bootable", "bootable/recovery", "build", "build/make",
    "build/soong", "device", "device/xiaomi/peridot", "device/voltage/sepolicy",
    "docs", "external", "frameworks", "frameworks/av", "frameworks/base",
    "frameworks/native", "frameworks/opt/telephony", "hardware",
    "hardware/xiaomi", "kernel", "manifest", "overlay", "packages",
    "packages/apps/Freezer", "packages/apps/Launcher3",
    "packages/apps/Powerhub", "packages/apps/Settings",
    "packages/apps/SetupWizard", "packages/apps/Updater", "prebuilts",
    "sepolicy", "system", "tools", "vendor", "vendor/bestrom", "vendor/voltage",
}

# Repo-local area names. LineageOS names the area after the module or the
# directory inside the repository being committed to ("Settings:", "base:",
# "peridot:"), not after its path in the combined tree, and the pushed history
# already reads that way. Kept apart from KNOWN_AREAS so the list of tree paths
# above stays a list of tree paths.
SHORT_AREAS = {
    "BestromAgent",
    "AndroidBlackTheme", "Freezer", "Launcher3", "LogViewer", "Powerhub",
    "Preinstaller", "Settings", "SettingsLib", "SetupWizard", "SystemUI",
    "Updater", "base", "check_boot_jars", "config", "fonts", "gen_build_prop",
    "peridot", "recovery", "soong",
}

# Release subjects written by the publish chain; they are deliberately not
# "area: Sentence-case".
RELEASE_SUBJECT_RE = re.compile(r"^(\d+: \S+|docs: latest release card \(.+\))$")

AI_VOCABULARY = (
    "comprehensive",
    "robust",
    "seamless",
    "seamlessly",
    "leverage",
    "leveraging",
    "delve",
    "cutting-edge",
    "state-of-the-art",
    "best-in-class",
    "elevate",
    "unlock the power",
    "game-changer",
    "game changer",
    "supercharge",
    "streamline",
    "enhance the experience",
    "meticulous",
    "meticulously",
    "it's worth noting",
    "in today's",
)

AI_TRAILER_PATTERNS = (
    re.compile(r"co-authored-by:\s*claude", re.IGNORECASE),
    re.compile(r"generated with \[?claude", re.IGNORECASE),
    re.compile(r"co-authored-by:.*noreply@anthropic\.com", re.IGNORECASE),
    re.compile(r"🤖"),
)

TRAILER_RE = re.compile(r"^[A-Z][A-Za-z-]+:\s")
APPROVED_TRAILERS = ("Signed-off-by:", "Change-Id:", "Fixes:", "Reverts:", "Bug:")

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U0000FE0F"
    "]"
)


def _violation(rule: str, severity: str, line: int, message: str, suggestion: str = "") -> StyleViolation:
    return StyleViolation(
        rule_id=rule, severity=severity, line=line, message=message, suggestion=suggestion
    )


def commit_message_check(text: str, strict: bool = False) -> StyleReport:
    lines = (text or "").rstrip("\n").split("\n")
    violations: list[StyleViolation] = []
    subject = lines[0].strip() if lines else ""
    area = ""

    if not subject:
        violations.append(_violation("subject-empty", "error", 1, "the commit has no subject"))
        return StyleReport(ok=False, subject="", area="", violations=violations)

    is_release_subject = bool(RELEASE_SUBJECT_RE.match(subject))

    if len(subject) > SUBJECT_HARD_LIMIT:
        violations.append(
            _violation(
                "subject-length-error", "error", 1,
                f"subject is {len(subject)} characters, the hard limit is {SUBJECT_HARD_LIMIT}",
                "cut the summary, do not continue it in the body",
            )
        )
    elif len(subject) > SUBJECT_SOFT_LIMIT:
        violations.append(
            _violation(
                "subject-length-warn", "warning", 1,
                f"subject is {len(subject)} characters; {SUBJECT_SOFT_LIMIT} reads better in git log",
            )
        )

    if subject.endswith("."):
        violations.append(
            _violation("subject-trailing-period", "error", 1, "subject ends with a period",
                       subject.rstrip("."))
        )

    match = re.match(r"^([A-Za-z0-9_./+-]+):\s+(\S.*)$", subject)
    if not match:
        if not is_release_subject:
            violations.append(
                _violation(
                    "subject-format", "error", 1,
                    "subject must be 'area: Sentence-case summary'",
                    "vendor: Add the BestROM MCP server",
                )
            )
    else:
        area = match.group(1)
        summary = match.group(2)
        if not is_release_subject:
            if area not in KNOWN_AREAS and area not in SHORT_AREAS:
                violations.append(
                    _violation(
                        "subject-area-unknown", "error", 1,
                        f"area {area!r} is not a tree path or a module in this tree",
                        "use the directory or module the change lives in, "
                        "e.g. vendor, frameworks/base or Settings",
                    )
                )
            if summary[:1].islower():
                violations.append(
                    _violation(
                        "subject-case", "error", 1,
                        "the summary after the area must start with a capital letter",
                        f"{area}: {summary[:1].upper()}{summary[1:]}",
                    )
                )

    if EMOJI_RE.search(subject):
        violations.append(_violation("emoji", "error", 1, "no emoji in commit messages"))

    body_lines: list[str] = []
    if len(lines) > 1:
        if lines[1].strip():
            violations.append(
                _violation("blank-second-line", "error", 2,
                           "the second line must be blank", "")
            )
            body_lines = lines[1:]
        else:
            body_lines = lines[2:]

    content = [line for line in body_lines if line.strip()]
    if not content:
        violations.append(
            _violation("body-missing", "warning", 2,
                       "no body; say why the change was made, in 1 to 6 lines")
        )
    elif len(body_lines) > BODY_MAX_LINES + body_lines.count(""):
        pass  # counted below on non-blank lines

    if len(content) > BODY_MAX_LINES:
        violations.append(
            _violation(
                "body-too-long", "error", 3,
                f"body is {len(content)} lines; keep it to {BODY_MAX_LINES}",
                "move the detail into the code or the changelog",
            )
        )

    for offset, line in enumerate(body_lines):
        line_no = offset + 3
        if len(line) > BODY_LIMIT:
            violations.append(
                _violation("body-line-length", "error", line_no,
                           f"body line is {len(line)} characters, wrap at {BODY_LIMIT}")
            )
        if EMOJI_RE.search(line):
            violations.append(_violation("emoji", "error", line_no, "no emoji in commit messages"))

    whole = "\n".join(lines)
    lowered = whole.lower()
    for word in AI_VOCABULARY:
        if word in lowered:
            violations.append(
                _violation(
                    "ai-vocabulary", "error", 1,
                    f"{word!r} does not appear anywhere in this project's history",
                    "say what changed in plain words",
                )
            )
    for pattern in AI_TRAILER_PATTERNS:
        if pattern.search(whole):
            violations.append(
                _violation(
                    "ai-trailer", "error", len(lines),
                    "AI attribution is not carried in the ROM repositories",
                    "delete the trailer",
                )
            )
            break

    for offset, line in enumerate(body_lines):
        stripped = line.strip()
        if TRAILER_RE.match(stripped) and not stripped.startswith(APPROVED_TRAILERS):
            if not any(p.search(stripped) for p in AI_TRAILER_PATTERNS):
                violations.append(
                    _violation(
                        "unapproved-trailer", "warning", offset + 3,
                        f"unrecognised trailer {stripped.split(':')[0]!r}",
                    )
                )

    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    ok = not errors and (not strict or not warnings)

    return StyleReport(
        ok=ok,
        subject=subject,
        area=area,
        violations=violations,
        suggested_message=suggest(subject, body_lines) if violations else whole,
    )


def _drop_ai_words(text: str) -> str:
    """Remove the forbidden vocabulary, leaving a sentence a human can finish."""
    out = text
    for word in AI_VOCABULARY:
        if word in out.lower():
            out = re.sub(r"\s*\b" + re.escape(word) + r"\b\s*", " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).replace(" ,", ",").strip()


def suggest(subject: str, body_lines: list[str]) -> str:
    """A mechanically repaired version of the message.

    Only fixes what can be fixed without inventing content: the trailing
    period, emoji, AI trailers and vocabulary, the wrap and the body length.
    """
    fixed_subject = _drop_ai_words(EMOJI_RE.sub("", subject)).strip().rstrip(".")
    match = re.match(r"^([A-Za-z0-9_./+-]+):\s+(\S.*)$", fixed_subject)
    if match and not RELEASE_SUBJECT_RE.match(fixed_subject):
        area, summary = match.group(1), match.group(2)
        fixed_subject = f"{area}: {summary[:1].upper()}{summary[1:]}"
    if len(fixed_subject) > SUBJECT_HARD_LIMIT:
        fixed_subject = fixed_subject[:SUBJECT_HARD_LIMIT].rstrip()

    kept: list[str] = []
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.search(stripped) for p in AI_TRAILER_PATTERNS):
            continue
        clean = _drop_ai_words(EMOJI_RE.sub("", stripped))
        if clean:
            kept.append(clean)

    wrapped: list[str] = []
    for line in kept:
        wrapped.extend(textwrap.wrap(line, width=BODY_LIMIT) or [])
    wrapped = wrapped[:BODY_MAX_LINES]

    if not wrapped:
        return fixed_subject + "\n"
    return fixed_subject + "\n\n" + "\n".join(wrapped) + "\n"


# -- strip_ai_trailers ---------------------------------------------------


def default_range(cfg: Config, path: Path, rel: str) -> str:
    """<remote>/<manifest revision>..HEAD, for a remote that actually exists.

    The publish set pushes to gh, bestrom and origin depending on the project,
    so a hardcoded origin/<rev> resolves to a nonexistent ref for
    device/xiaomi/peridot and frameworks/base and the scan silently returns
    "git log failed" instead of results.
    """
    from .repo import manifest_path, parse_manifest

    revision = parse_manifest(manifest_path(cfg)).get(rel, "")
    if not revision:
        return "HEAD~50..HEAD"

    candidates: list[str] = []
    for spec in cfg.push_projects:
        parts = spec.split()
        if len(parts) >= 2 and parts[0] == rel:
            candidates.append(parts[1])
    candidates.extend(r for r in ("origin", "gh", "bestrom") if r not in candidates)

    for remote in candidates:
        ref = f"{remote}/{revision}"
        if proc.run(["git", "-C", str(path), "rev-parse", "--verify", "-q", ref], timeout=20).ok:
            return f"{ref}..HEAD"
    return "HEAD~50..HEAD"


def strip_ai_trailers(cfg: Config, repo: str, since: str = "") -> TrailerScan:
    try:
        path = cfg.resolve_allowed(repo, must_exist=True)
    except ValueError as exc:
        return TrailerScan(repo=repo, note=str(exc))
    if not (path / ".git").exists():
        return TrailerScan(repo=str(path), note="not a git checkout")

    if not since:
        try:
            rel = str(path.relative_to(cfg.tree.root))
        except ValueError:
            rel = ""
        since = default_range(cfg, path, rel)
    # fullmatch, and no leading dash: "--all" otherwise passes straight into
    # git log's argv as an option rather than as a range.
    if since.startswith("-") or not re.fullmatch(
        r"[A-Za-z0-9_./~^{}][A-Za-z0-9_./~^{}-]*(\.\.[A-Za-z0-9_./~^{}][A-Za-z0-9_./~^{}-]*)?",
        since,
    ):
        return TrailerScan(repo=str(path), note="invalid range")

    result = proc.run(
        ["git", "-C", str(path), "log", "--format=%H%x00%s%x00%b%x1e", since],
        timeout=120,
    )
    if not result.ok and not result.out:
        return TrailerScan(
            repo=str(path), range=since,
            note=f"git log failed: {result.err.strip()[:200]}",
        )

    commits: list[TrailerCommit] = []
    for record in result.out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split("\x00")
        if len(parts) < 3:
            continue
        sha, subject, body = parts[0], parts[1], parts[2]
        offending = [
            line.strip()
            for line in (subject + "\n" + body).splitlines()
            if any(p.search(line) for p in AI_TRAILER_PATTERNS)
        ]
        if offending:
            commits.append(
                TrailerCommit(sha=sha[:12], subject=subject, offending_lines=offending)
            )

    rewrite = (
        "git -C "
        + shlex.quote(str(path))
        + " filter-repo --force --message-callback '\n"
        "import re\n"
        "msg = message.decode(\"utf-8\", \"replace\")\n"
        "msg = re.sub(r\"(?im)^\\\\s*co-authored-by:\\\\s*claude.*$\\\\n?\", \"\", msg)\n"
        "msg = re.sub(r\"(?im)^.*generated with \\\\[?claude.*$\\\\n?\", \"\", msg)\n"
        "return msg.rstrip().encode() + b\"\\\\n\"\n"
        "'"
    )

    return TrailerScan(
        repo=str(path),
        range=since,
        commits=commits,
        count=len(commits),
        rewrite_command=rewrite if commits else "",
        note=(
            "This tool never rewrites history. Run the command above yourself, "
            "on a branch you can throw away, and force-push deliberately. "
            "It needs git-filter-repo, which is a separate install."
        ),
    )
