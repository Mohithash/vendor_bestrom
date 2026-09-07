"""device_list, device_capture, device_sideload.

Everything here goes through one guard: nothing runs ``adb`` until ``ss -ltn``
shows a listener on the configured port. ``adb -P <port>`` against an unbound
port silently starts a local adb server that squats the port, and the reverse
SSH tunnel can then never bind it again.
"""

from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

from .. import proc
from ..config import Config
from ..models import (
    CaptureResult,
    CaptureSummary,
    DeviceEntry,
    DeviceList,
    SideloadPlan,
)
from .env import port_listener

CAPTURE_KINDS = ("crashes", "logcat", "dropbox", "screenshot", "avc", "packages")
# fullmatch, not match: "$" in Python also matches before a trailing newline, so
# re.match would accept "com.foo\n" and that newline terminates the command
# line on the device.
PACKAGE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")

DEVICE_PROPS = (
    "ro.build.version.incremental",
    "ro.bestrom.version",
    "ro.bestrom.build.status",
    "ro.build.fingerprint",
)

DROPBOX_TAGS = (
    "system_app_crash",
    "data_app_crash",
    "system_server_crash",
    "system_app_anr",
    "data_app_anr",
    "system_server_anr",
    "system_server_wtf",
    "system_app_wtf",
    "SYSTEM_TOMBSTONE",
    "system_app_native_crash",
    "data_app_native_crash",
)


class PortUnbound(RuntimeError):
    pass


def _adb_env(cfg: Config) -> dict[str, str]:
    return {"ADB_SERVER_SOCKET": f"tcp:{cfg.device.adb_host}:{cfg.device.adb_port}"}


def _adb(cfg: Config, args: list[str], timeout: int | None = None) -> proc.ProcResult:
    listener, _ = port_listener(cfg.device.adb_port)
    if not listener:
        raise PortUnbound(
            f"nothing is listening on {cfg.device.adb_host}:{cfg.device.adb_port}. "
            "Refusing to run adb: adb -P on an unbound port starts a local daemon "
            "that squats the port and the reverse tunnel can then never bind. "
            "Bring the tunnel up first (ssh -R), then retry."
        )
    timeout = timeout or cfg.device.default_timeout_s
    timeout = max(5, min(int(timeout), cfg.device.max_timeout_s))
    return proc.run(
        ["adb", "-P", str(cfg.device.adb_port), *args],
        timeout=timeout,
        env=_adb_env(cfg),
    )


def _shell(cfg: Config, command: str, timeout: int | None = None) -> proc.ProcResult:
    return _adb(cfg, ["-s", cfg.device.serial, "shell", command], timeout=timeout)


def _root_shell(cfg: Config, command: str, root: bool, timeout: int | None = None) -> proc.ProcResult:
    if root:
        # shlex.quote, not repr: repr emits Python escapes (\n, \t, doubled
        # backslashes, double quotes around a value containing an apostrophe)
        # which the device's sh reads under different rules.
        return _shell(cfg, "su -c " + shlex.quote(command), timeout=timeout)
    return _shell(cfg, command, timeout=timeout)


def _props_command() -> str:
    """Emit key=value from the device rather than relying on line order.

    `getprop <unset>` prints an empty line, so dropping blanks and mapping by
    position shifted every later value up one - which is exactly the state a
    phone is in after a flash that did not take.
    """
    names = " ".join(DEVICE_PROPS)
    return (
        f'for p in {names}; do echo "$p=$(getprop $p)"; done; '
        'echo "selinux=$(getenforce)"; echo "uptime=$(uptime)"'
    )


def _parse_props(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


# -- device_list ---------------------------------------------------------


def device_list(cfg: Config) -> DeviceList:
    listener, owner = port_listener(cfg.device.adb_port)
    if not listener:
        return DeviceList(
            port=cfg.device.adb_port,
            listener_present=False,
            unreachable_reason=(
                f"no listener on {cfg.device.adb_host}:{cfg.device.adb_port}. "
                "adb was NOT run: calling adb -P on an unbound port spawns a daemon "
                "that steals the tunnel port. Bring up the reverse tunnel first."
            ),
        )

    devices_out = _adb(cfg, ["devices", "-l"], timeout=30)
    devices: list[DeviceEntry] = []
    for line in devices_out.out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append(
                DeviceEntry(
                    serial=parts[0],
                    state=parts[1],
                    is_configured_serial=parts[0] == cfg.device.serial,
                )
            )

    report = DeviceList(
        port=cfg.device.adb_port,
        listener_present=True,
        listener_owner=owner,
        devices=devices,
    )
    if not any(d.state == "device" for d in devices):
        report.unreachable_reason = "the port is bound but no device is in state 'device'"
        return report

    props_out = _shell(cfg, _props_command(), timeout=45)
    parsed = _parse_props(props_out.out)
    for key in DEVICE_PROPS:
        report.props[key] = parsed.get(key, "")
    report.selinux = parsed.get("selinux", "")
    report.uptime = parsed.get("uptime", "")
    absent = [key for key in DEVICE_PROPS if not report.props[key]]
    if absent:
        report.unreachable_reason = (
            "these properties are not set on the device: "
            + ", ".join(absent)
            + " - it may not be running BestROM"
        )

    root = _shell(cfg, "su -c id", timeout=20)
    report.root_via_su = "uid=0" in root.out
    if not report.root_via_su:
        report.unreachable_reason = (
            "no adb root on this user build: /data/tombstones and root-gated dumps "
            "come back empty, which is not the same as no crashes"
        )
    return report


# -- device_capture ------------------------------------------------------


def _evidence_dir(cfg: Config, out_dir: str) -> Path:
    if out_dir:
        target = cfg.resolve_allowed(out_dir)
        root = cfg.device.evidence_dir.resolve()
        try:
            target.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(f"out_dir must live under {root}") from exc
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
        target = cfg.device.evidence_dir / stamp
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write(target: Path, name: str, text: str) -> str:
    path = target / name
    path.write_text(text, encoding="utf-8")
    return name


def device_capture(
    cfg: Config,
    kind: str,
    package: str = "",
    timeout_s: int = 60,
    out_dir: str = "",
) -> CaptureResult:
    if kind not in CAPTURE_KINDS:
        return CaptureResult(kind=kind, refused_reason=f"kind must be one of {CAPTURE_KINDS}")
    if package and (package.startswith("-") or not PACKAGE_RE.fullmatch(package)):
        return CaptureResult(kind=kind, refused_reason="package is not a valid package name")
    timeout_s = max(10, min(int(timeout_s), cfg.device.max_timeout_s))

    listener, _ = port_listener(cfg.device.adb_port)
    if not listener:
        return CaptureResult(
            kind=kind,
            refused_reason=(
                f"no listener on port {cfg.device.adb_port}; adb was not run "
                "(it would spawn a daemon that steals the tunnel port)"
            ),
        )

    try:
        target = _evidence_dir(cfg, out_dir)
    except ValueError as exc:
        return CaptureResult(kind=kind, refused_reason=str(exc))

    if package:
        listing = _shell(cfg, "pm list packages", timeout=60)
        installed = {line.strip()[len("package:") :] for line in listing.out.splitlines()
                     if line.strip().startswith("package:")}
        # line-exact: the old substring test matched com.foo inside com.foobar
        if package not in installed:
            return CaptureResult(
                kind=kind, out_dir=str(target),
                refused_reason=f"{package} is not installed on the device",
            )

    root_probe = _shell(cfg, "su -c id", timeout=20)
    root = "uid=0" in root_probe.out
    summary = CaptureSummary(root_used=root)
    files: list[str] = []
    failed: list[str] = []

    if kind == "dropbox":
        listing = _shell(cfg, "dumpsys dropbox", timeout=min(timeout_s, 120))
        files.append(_write(target, "dropbox-list.txt", listing.out))
        counts: dict[str, int] = {}
        for tag in DROPBOX_TAGS:
            hits = len(re.findall(re.escape(tag), listing.out))
            if hits:
                counts[tag] = hits
        summary.tag_histogram = [
            f"{count:5d} {tag}" for tag, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]

    elif kind == "crashes":
        printed = _shell(cfg, "dumpsys dropbox --print", timeout=cfg.device.max_timeout_s)
        files.append(_write(target, "dropbox-print.txt", printed.out))
        summary.crash_summary = _crash_rollup(printed.out)
        summary.truncated = printed.truncated or printed.timed_out
        crash_buf = _shell(cfg, "logcat -d -b crash", timeout=min(timeout_s, 120))
        files.append(_write(target, "logcat-crash.txt", crash_buf.out))
        summary.fatal_count = crash_buf.out.count("FATAL EXCEPTION")
        listing = _root_shell(cfg, "ls -la /data/tombstones/ 2>/dev/null | tail -20", root)
        files.append(_write(target, "tombstones-ls.txt", listing.out))

    elif kind == "logcat":
        command = "logcat -d" if not package else f"logcat -d | grep -a {package}"
        main = _shell(cfg, command, timeout=timeout_s)
        files.append(_write(target, "logcat-main.txt", main.out))
        events = _shell(
            cfg,
            "logcat -d -b events | grep -aE 'am_crash|am_anr|am_wtf|am_proc_died|am_kill'",
            timeout=min(timeout_s, 120),
        )
        files.append(_write(target, "logcat-events.txt", events.out))
        summary.fatal_count = main.out.count("FATAL EXCEPTION")
        summary.truncated = main.truncated

    elif kind == "avc":
        avc = _root_shell(
            cfg,
            "logcat -d | grep -a 'avc: *denied' | sed -E 's/audit\\([^)]*\\)//' "
            "| sort | uniq -c | sort -rn | head -25",
            root,
            timeout=min(timeout_s, 120),
        )
        files.append(_write(target, "avc.txt", avc.out))
        summary.avc_histogram = [line.strip() for line in avc.out.splitlines() if line.strip()][:25]

    elif kind == "screenshot":
        remote = "/sdcard/bestrom-mcp-capture.png"
        _shell(cfg, f"screencap -p {remote}", timeout=min(timeout_s, 60))
        pull = _adb(
            cfg,
            ["-s", cfg.device.serial, "pull", remote, str(target / "screen.png")],
            timeout=min(timeout_s, 120),
        )
        _shell(cfg, f"rm -f {remote}", timeout=20)
        if (target / "screen.png").is_file():
            files.append("screen.png")
        else:
            summary.truncated = True
            failed.append(f"screen.png not pulled: {pull.err.strip()[:200]}")

    elif kind == "packages":
        system = _shell(cfg, "pm list packages -s", timeout=min(timeout_s, 120))
        third = _shell(cfg, "pm list packages -3", timeout=min(timeout_s, 120))
        disabled = _shell(cfg, "pm list packages -d", timeout=min(timeout_s, 120))
        files.append(_write(target, "packages-system.txt", system.out))
        files.append(_write(target, "packages-third-party.txt", third.out))
        files.append(_write(target, "packages-disabled.txt", disabled.out))
        summary.package_counts = {
            "system": len(system.out.splitlines()),
            "third_party": len(third.out.splitlines()),
            "disabled": len([line for line in disabled.out.splitlines() if line.strip()]),
        }

    # device.txt and crash-summary.txt are what bestrom://device-evidence/latest
    # renders. The older crash-sweep/capture.sh wrote them; without them a
    # capture the server made itself showed up in the resource as a bare index.
    header = _shell(cfg, _props_command(), timeout=45)
    device_lines = [f"serial: {cfg.device.serial}", f"root available: {root}", ""]
    device_lines.extend(header.out.splitlines())
    files.append(_write(target, "device.txt", "\n".join(device_lines) + "\n"))
    if summary.crash_summary:
        files.append(
            _write(target, "crash-summary.txt", "\n".join(summary.crash_summary) + "\n")
        )

    index = [
        f"kind: {kind}",
        f"captured: {datetime.now(timezone.utc).isoformat()}",
        f"root available: {root}",
        "files: " + ", ".join(files),
    ]
    if failed:
        index.append("failed: " + "; ".join(failed))
    _write(target, "index.txt", "\n".join(index) + "\n")
    files.append("index.txt")

    return CaptureResult(
        kind=kind, out_dir=str(target), files=files, failed=failed, summary=summary
    )


def _crash_rollup(text: str, limit: int = 40) -> list[str]:
    """process :: first exception line, most frequent first."""
    counts: dict[str, int] = {}
    process = ""
    in_header = False
    exception = re.compile(
        r"^(java\.|android\.|kotlin\.|[A-Za-z.]+Exception|[A-Za-z.]+Error)"
    )
    for line in text.splitlines():
        if line.startswith("========================================"):
            in_header = True
            continue
        if not in_header:
            continue
        if line.startswith("Process:"):
            parts = line.split()
            process = parts[1] if len(parts) > 1 else ""
            continue
        if exception.match(line):
            key = f"{process} :: {line.strip()[:200]}"
            counts[key] = counts.get(key, 0) + 1
            in_header = False
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [f"{count:5d} {key}" for key, count in ranked[:limit]]


# -- device_sideload -----------------------------------------------------


def device_sideload(
    cfg: Config,
    zip_path: str = "",
    images: list[str] | None = None,
    confirm: bool = False,
    dry_run: bool = True,
    allow_remote: bool = False,
) -> SideloadPlan:
    images = [i for i in (images or []) if i]
    allowed_images = {"boot", "vendor_boot"}
    bad = [i for i in images if i not in allowed_images]
    if bad:
        return SideloadPlan(
            dry_run=dry_run,
            refused_reason=f"images must be a subset of {sorted(allowed_images)}; got {bad}",
        )

    from .build import newest_zip, zip_info
    from .release import read_marker_zip

    target = None
    if zip_path:
        try:
            target = cfg.resolve_allowed(zip_path, must_exist=True)
        except ValueError as exc:
            return SideloadPlan(dry_run=dry_run, refused_reason=str(exc))
    else:
        target = newest_zip(cfg)

    info = zip_info(target)
    # In every refused case this still hands back the exact local command, so
    # the maintainer never has to reconstruct it from the refusal text.
    commands: list[str] = ["adb reboot sideload"]
    if target is not None:
        commands.append(f"adb sideload {target}")
    else:
        commands.append(f"adb sideload {cfg.tree.out / '<package>.zip'}  # nothing built yet")
    for image in images:
        commands.append(f"fastboot flash {image} {cfg.tree.out / (image + '.img')}")

    paired_ok = not images or set(images) == allowed_images
    if images and not paired_ok:
        return SideloadPlan(
            dry_run=dry_run,
            local_commands=commands,
            zip=info,
            paired_images_ok=False,
            refused_reason=(
                "refusing: boot.img and vendor_boot.img must be flashed together. "
                "Flashing boot alone is how the QRTR sensor bootloop was reproduced."
            ),
        )

    verified_name = read_marker_zip(cfg)
    if target is not None and verified_name and target.name != verified_name:
        return SideloadPlan(
            dry_run=dry_run, local_commands=commands, zip=info,
            refused_reason=(
                f"refusing: {target.name} is not the package the verify gate passed "
                f"({verified_name}). Run verify_image first."
            ),
        )

    state = ""
    listener, _ = port_listener(cfg.device.adb_port)
    if listener:
        try:
            devices = _adb(cfg, ["devices"], timeout=30)
            state = "reachable" if cfg.device.serial in devices.out else "not attached"
        except PortUnbound:
            state = "port unbound"
    else:
        state = "port unbound"

    remote_allowed = allow_remote and cfg.device.allow_remote_sideload
    if not remote_allowed:
        return SideloadPlan(
            dry_run=dry_run, local_commands=commands, zip=info, device_state=state,
            paired_images_ok=paired_ok,
            refused_reason=(
                "remote sideload is disabled. A 2.7 GB package over the reverse tunnel "
                "runs at ~0.7 MB/s and drops before it finishes, leaving the phone in "
                "recovery with a half-written update. Run the commands below on the "
                "machine the phone is plugged into."
            ),
        )
    if dry_run or not confirm:
        return SideloadPlan(
            dry_run=dry_run, local_commands=commands, zip=info, device_state=state,
            paired_images_ok=paired_ok,
            refused_reason="dry_run=false and confirm=true are both required to flash",
        )

    result = _adb(cfg, ["-s", cfg.device.serial, "sideload", str(target)], timeout=cfg.device.max_timeout_s)
    return SideloadPlan(
        dry_run=False, local_commands=commands, zip=info,
        device_state=("sideload ok" if result.ok else f"sideload failed rc={result.rc}"),
        paired_images_ok=paired_ok,
        refused_reason="" if result.ok else result.err.strip()[:300],
    )
