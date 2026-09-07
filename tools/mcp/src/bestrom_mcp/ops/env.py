"""env_check — one read-only preflight before anything expensive."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .. import jobs, proc
from ..config import Config
from ..models import BuildInFlight, CcacheStats, EnvReport

OUT_SIZE_CACHE_S = 3600


def _disk_free_gb(path: Path) -> int:
    try:
        stat = os.statvfs(path)
    except OSError:
        return -1
    return int(stat.f_bavail * stat.f_frsize / 1024**3)


def _mem_available_gb() -> int:
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return -1
    match = re.search(r"^MemAvailable:\s+(\d+) kB", text, re.MULTILINE)
    return int(int(match.group(1)) / 1024**2) if match else -1


def _out_size_gb(cfg: Config) -> float:
    """du on a 140 GB out/ is slow, so the answer is cached for an hour."""
    cache = cfg.state_dir / "out-size.json"
    now = time.time()
    if cache.is_file():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if now - float(data.get("at", 0)) < OUT_SIZE_CACHE_S:
                return float(data.get("size_gb", -1))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    out = cfg.tree.root / "out"
    if not out.is_dir():
        return 0.0
    result = proc.run(["du", "-sb", str(out)], timeout=180)
    if not result.ok:
        return -1.0
    try:
        size_gb = round(int(result.out.split()[0]) / 1024**3, 1)
    except (IndexError, ValueError):
        return -1.0
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"size_gb": size_gb, "at": now}), encoding="utf-8")
    except OSError:
        pass
    return size_gb


def _ccache() -> CcacheStats:
    if not proc.which("ccache"):
        return CcacheStats()
    result = proc.run(["ccache", "-s"], timeout=30)
    hit = ""
    cacheable = ""
    for line in result.out.splitlines():
        low = line.lower()
        if "hits:" in low and "%" in line and not hit:
            hit = line.strip()
        if "cacheable calls" in low and not cacheable:
            cacheable = line.strip()
    return CcacheStats(hit_rate=hit, cacheable=cacheable)


def port_listener(port: int) -> tuple[bool, str]:
    """Is anything listening on *port*? Uses ``ss -ltn``, never adb.

    Calling ``adb -P <port>`` before sshd has bound the port starts a local adb
    daemon that squats it, and the reverse tunnel can then never bind. Every
    device tool asks this question first.
    """
    result = proc.run(["ss", "-ltnp"], timeout=20)
    if not result.out:
        result = proc.run(["ss", "-ltn"], timeout=20)
    needle = f":{port} "
    for line in result.out.splitlines():
        if needle in line + " ":
            owner = ""
            match = re.search(r'users:\(\("([^"]+)"', line)
            if match:
                owner = match.group(1)
            return True, owner
    return False, ""


def env_check(cfg: Config) -> EnvReport:
    root = cfg.tree.root
    blockers: list[str] = []

    cores = os.cpu_count() or 0
    mem_gb = _mem_available_gb()
    disk_gb = _disk_free_gb(root if root.exists() else Path("/"))
    out_gb = _out_size_gb(cfg)
    headroom_ok = disk_gb >= cfg.tree.min_free_gb

    envsetup = (root / "build" / "envsetup.sh").exists()
    makefile = (root / "Makefile").exists()

    products = root / "device" / "xiaomi" / "peridot" / "AndroidProducts.mk"
    lunch_ok = False
    if products.is_file():
        try:
            lunch_ok = "bestrom_peridot" in products.read_text(encoding="utf-8", errors="replace")
        except OSError:
            lunch_ok = False

    repo_version = ""
    if proc.which("repo"):
        result = proc.run(["repo", "--version"], cwd=root, timeout=30)
        for line in result.out.splitlines():
            if line.lower().startswith("repo launcher version"):
                repo_version = line.strip()
                break
        if not repo_version:
            repo_version = result.out.splitlines()[0].strip() if result.out else ""

    running, which_proc = jobs.build_in_flight()
    registry = jobs.Registry.load(cfg.state_dir)
    newest = registry.newest()
    in_flight = BuildInFlight(
        running=running,
        unit=(newest.unit if running and newest else ""),
        log=(newest.log_path if running and newest else ""),
    )

    systemd_ok = jobs.systemd_user_ok()
    listener, _owner = port_listener(cfg.device.adb_port)

    # Prebuilts that are fetched rather than committed. Not a blocker: the
    # build wrapper runs tools/fetch-prebuilts.sh before lunch, so a missing
    # file is a warning here and an error only if the fetch itself failed.
    warnings: list[str] = []
    webview = root / "vendor" / "bestrom" / "prebuilt" / "CromiteWebView" / "CromiteWebView.apk"
    prebuilts_present = webview.is_file()
    if not prebuilts_present:
        warnings.append(
            "vendor/bestrom/prebuilt/CromiteWebView/CromiteWebView.apk is missing; "
            "config/branding.mk hard-errors without it. build-bestrom-run.sh fetches "
            "it, or run vendor/bestrom/tools/fetch-prebuilts.sh by hand."
        )

    if not root.is_dir():
        blockers.append(f"tree root {root} does not exist")
    if not envsetup:
        blockers.append("build/envsetup.sh missing - run tree_repair")
    if not makefile:
        blockers.append("./Makefile missing - run tree_repair")
    if not lunch_ok:
        blockers.append("bestrom_peridot not found in device/xiaomi/peridot/AndroidProducts.mk")
    if not headroom_ok:
        blockers.append(
            f"only {disk_gb} GB free, {cfg.tree.min_free_gb} GB required - a build will die on ENOSPC"
        )
    if not systemd_ok:
        blockers.append("systemd --user is not usable; build_start cannot detach a job")
    if running:
        blockers.append(f"a build is already in flight ({which_proc} is running)")

    return EnvReport(
        tree=str(root),
        ok=not blockers,
        cores=cores,
        mem_available_gb=mem_gb,
        disk_free_gb=disk_gb,
        out_size_gb=out_gb,
        headroom_ok=headroom_ok,
        ccache=_ccache(),
        repo_version=repo_version,
        envsetup_present=envsetup,
        makefile_present=makefile,
        lunch_target_available=lunch_ok,
        systemd_user_ok=systemd_ok,
        build_in_flight=in_flight,
        adb_port_listener=listener,
        prebuilts_present=prebuilts_present,
        blockers=blockers,
        warnings=warnings,
    )
