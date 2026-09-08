"""Configuration for the BestROM MCP server.

Precedence, lowest first:

1. structural defaults in this module (the tree root, derived by walking up
   from the package directory; nothing machine-specific is hardcoded);
2. the shipped ``bestrom.toml`` next to ``pyproject.toml``;
3. a user TOML named by ``$BESTROM_MCP_CONFIG``;
4. ``BESTROM_MCP_<SECTION>_<KEY>`` environment variables.

No credential is read from or written to the configuration.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

PKG_DIR = Path(__file__).resolve().parent


def _server_dir() -> Path:
    """Directory holding bestrom.toml and profiles/ (vendor/bestrom/tools/mcp)."""
    for candidate in [PKG_DIR, *PKG_DIR.parents[:6]]:
        if (candidate / "bestrom.toml").is_file():
            return candidate
    return PKG_DIR


SERVER_DIR = _server_dir()


def _default_tree_root() -> Path:
    """vendor/bestrom/tools/mcp -> four levels up is the tree root."""
    parents = SERVER_DIR.parents
    if len(parents) >= 4:
        return parents[3]
    return SERVER_DIR


class ConfigError(ValueError):
    """Raised when the configuration itself is unusable."""


class PathNotAllowed(ValueError):
    """Raised when a filesystem argument escapes the allowlist."""


@dataclass(frozen=True)
class TreeCfg:
    root: Path
    out_dir: str = "out/target/product/peridot"
    logs_dir: Path = Path("/serverhive1/sal/bootloop-logs")
    dl_dir: Path = Path("/serverhive1/sal/dl")
    min_free_gb: int = 200

    @property
    def out(self) -> Path:
        return self.root / self.out_dir


@dataclass(frozen=True)
class BuildCfg:
    script: str = "build-bestrom-run.sh"
    lunch: str = "bestrom_peridot-cp2a-user"
    goal: str = "bestrom"
    jobs: int = 64
    official: bool = True
    unit_prefix: str = "bestrom-build-"
    log_prefix: str = "build-"
    zip_glob: str = "BestROM-*-OFFICIAL.zip"


@dataclass(frozen=True)
class VerifyCfg:
    profile: str = "peridot"
    profiles_dir: str = "profiles"
    marker_dir: Path = Path("/serverhive1/sal/bootloop-logs")


@dataclass(frozen=True)
class DeviceCfg:
    adb_port: int = 15038
    adb_host: str = "127.0.0.1"
    serial: str = "bc94484f"
    default_timeout_s: int = 60
    max_timeout_s: int = 300
    evidence_dir: Path = Path("/serverhive1/sal/bootloop-logs/crash-sweep")
    allow_remote_sideload: bool = False


@dataclass(frozen=True)
class AgentCfg:
    """The Agent mode bridge on the phone.

    Nothing here is a credential. The pairing secret the phone hands out lives
    in the state directory with mode 0600 and is never printed, returned or
    configured.
    """

    port: int = 8765
    socket: str = "bestrom_agent"
    package: str = "com.bestrom.agent"
    connect_timeout_s: int = 5
    request_timeout_s: int = 30
    max_request_timeout_s: int = 120
    # Empty in the TOML means "use [device] evidence_dir"; it is resolved to a
    # real path at load time so no tool has to know about the fallback.
    evidence_dir: Path = Path("/serverhive1/sal/bootloop-logs/crash-sweep")
    evidence_subdir: str = "agent"
    state_file: str = "agent-pairing.json"
    inline_node_limit: int = 200

    @property
    def evidence_root(self) -> Path:
        return self.evidence_dir / self.evidence_subdir if self.evidence_subdir else self.evidence_dir


@dataclass(frozen=True)
class ReleaseCfg:
    chains: tuple[str, ...] = ("sweep", "aperture", "miuicamera", "hardening")
    sourceforge_project: str = "bestrom"
    sourceforge_frs_path: str = "/home/frs/project/bestrom/peridot/"
    sourceforge_web_path: str = "/home/project-web/bestrom/htdocs/index.html"
    ota_repo: Path = Path("/serverhive1/sal/bootloop-logs/bestrom_ota")
    ota_branch: str = "17"
    site_repo: Path = Path("/serverhive1/sal/bootloop-logs/bestrom-project")
    pages_dir: Path = Path("/serverhive1/sal/bootloop-logs/sf-release/pages")
    publish_timeout_s: int = 3600
    # Facts for the release header. Empty means "unknown": release_prepare says
    # so in the draft rather than printing a stale kernel version as fact.
    kernel: str = ""
    base: str = ""


# The tools that refuse without confirm=true. This is a description of what the
# code does, not a switch: each refusal is written into the tool itself, so a
# name added here would change nothing. It exists so bestrom://config reports
# the real list and an auditor can check it against the source.
CONFIRM_REQUIRED_TOOLS = (
    "repo_sync",
    "build_cancel",
    "device_sideload",
    "release_publish",
    "device_agent_execute",
    "device_agent_tap",
    "device_agent_long_press",
    "device_agent_swipe",
    "device_agent_type",
    "device_agent_key",
    "device_agent_launch",
    "device_agent_log",
    "device_agent_stop",
)

# A tree root has to look like one. Without this, a client that passes an
# unexpanded ${VAR} through BESTROM_TREE starts the server happily and every
# later tool fails with an unrelated "outside the allowlist".
TREE_MARKERS = ("build/make", "vendor/bestrom")


@dataclass(frozen=True)
class SafetyCfg:
    allowlist_roots: tuple[Path, ...] = ()
    enable_publish: bool = True


@dataclass(frozen=True)
class Config:
    tree: TreeCfg
    build: BuildCfg = field(default_factory=BuildCfg)
    verify: VerifyCfg = field(default_factory=VerifyCfg)
    device: DeviceCfg = field(default_factory=DeviceCfg)
    agent: AgentCfg = field(default_factory=AgentCfg)
    release: ReleaseCfg = field(default_factory=ReleaseCfg)
    safety: SafetyCfg = field(default_factory=SafetyCfg)
    push_projects: tuple[str, ...] = ()
    state_dir: Path = SERVER_DIR / "state"
    server_dir: Path = SERVER_DIR
    sources: tuple[str, ...] = ()

    # -- paths -----------------------------------------------------------

    @property
    def profiles_path(self) -> Path:
        return self.server_dir / self.verify.profiles_dir

    def resolve_allowed(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve *path* and require it to sit inside an allowlist root.

        Symlinks are resolved before the check and ``..`` cannot escape,
        because ``Path.resolve()`` normalises both.
        """
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.tree.root / candidate
        resolved = candidate.resolve()
        for root in self.safety.allowlist_roots:
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                continue
            if must_exist and not resolved.exists():
                raise PathNotAllowed(f"path does not exist: {resolved}")
            return resolved
        roots = ", ".join(str(r) for r in self.safety.allowlist_roots)
        raise PathNotAllowed(f"path {resolved} is outside the allowlist ({roots})")

    def redacted_dict(self) -> dict[str, Any]:
        """The effective configuration, for the bestrom://config resource."""
        return {
            "tree": {
                "root": str(self.tree.root),
                "out_dir": self.tree.out_dir,
                "out": str(self.tree.out),
                "logs_dir": str(self.tree.logs_dir),
                "dl_dir": str(self.tree.dl_dir),
                "min_free_gb": self.tree.min_free_gb,
            },
            "build": {
                "script": self.build.script,
                "lunch": self.build.lunch,
                "goal": self.build.goal,
                "jobs": self.build.jobs,
                "official": self.build.official,
                "unit_prefix": self.build.unit_prefix,
                "log_prefix": self.build.log_prefix,
                "zip_glob": self.build.zip_glob,
            },
            "verify": {
                "profile": self.verify.profile,
                "profiles_dir": str(self.profiles_path),
                "marker_dir": str(self.verify.marker_dir),
            },
            "device": {
                "adb_host": self.device.adb_host,
                "adb_port": self.device.adb_port,
                "serial": self.device.serial,
                "default_timeout_s": self.device.default_timeout_s,
                "max_timeout_s": self.device.max_timeout_s,
                "evidence_dir": str(self.device.evidence_dir),
                "allow_remote_sideload": self.device.allow_remote_sideload,
            },
            "agent": {
                "port": self.agent.port,
                "socket": self.agent.socket,
                "package": self.agent.package,
                "connect_timeout_s": self.agent.connect_timeout_s,
                "request_timeout_s": self.agent.request_timeout_s,
                "max_request_timeout_s": self.agent.max_request_timeout_s,
                "evidence_root": str(self.agent.evidence_root),
                # The path of the pairing state file, never its contents. It is
                # mode 0600 and nothing in this server reads it back out to a
                # caller.
                "pairing_state_file": str(self.state_dir / self.agent.state_file),
                "inline_node_limit": self.agent.inline_node_limit,
            },
            "release": {
                "chains": list(self.release.chains),
                "sourceforge_project": self.release.sourceforge_project,
                "sourceforge_frs_path": self.release.sourceforge_frs_path,
                "sourceforge_web_path": self.release.sourceforge_web_path,
                "ota_repo": str(self.release.ota_repo),
                "ota_branch": self.release.ota_branch,
                "site_repo": str(self.release.site_repo),
                "pages_dir": str(self.release.pages_dir),
                "publish_timeout_s": self.release.publish_timeout_s,
                "kernel": self.release.kernel,
                "base": self.release.base,
            },
            "push": {"projects": list(self.push_projects)},
            "safety": {
                "allowlist_roots": [str(p) for p in self.safety.allowlist_roots],
                "confirm_required": list(CONFIRM_REQUIRED_TOOLS),
                "enable_publish": self.safety.enable_publish,
                "destructive_enabled": {
                    "repo_sync": True,
                    "build_cancel": True,
                    "device_sideload": self.device.allow_remote_sideload,
                    "release_publish": self.safety.enable_publish,
                },
            },
            "state_dir": str(self.state_dir),
            "config_sources": list(self.sources),
        }


# -- loading -------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _env_overlay(environ: dict[str, str]) -> dict[str, Any]:
    """BESTROM_MCP_<SECTION>_<KEY> -> {"section": {"key": value}}."""
    sections = {"tree", "build", "verify", "device", "agent", "release", "push", "safety"}
    overlay: dict[str, Any] = {}
    for name, raw in environ.items():
        if not name.startswith("BESTROM_MCP_"):
            continue
        rest = name[len("BESTROM_MCP_") :].lower()
        section, _, key = rest.partition("_")
        if section not in sections or not key:
            continue
        overlay.setdefault(section, {})[key] = raw
    return overlay


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc


def _as_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return tuple(part for part in str(value).split(",") if part.strip())


def tree_root_problem(root: Path) -> str:
    """Why *root* cannot be an Android tree, or "" if it looks like one."""
    if not root.is_dir():
        return f"tree root {root} is not a directory"
    if not any((root / marker).exists() for marker in TREE_MARKERS):
        return (
            f"tree root {root} contains neither "
            + " nor ".join(TREE_MARKERS)
            + ". Set BESTROM_TREE to the checkout root, or drop it and let the "
            "server derive the root from its own location."
        )
    return ""


def load_config(
    config_path: str | Path | None = None,
    environ: dict[str, str] | None = None,
    require_tree: bool = False,
) -> Config:
    environ = dict(os.environ if environ is None else environ)
    sources: list[str] = ["defaults"]

    data: dict[str, Any] = {}
    shipped = SERVER_DIR / "bestrom.toml"
    if shipped.is_file():
        data = _merge(data, _load_toml(shipped))
        sources.append(str(shipped))

    user_path = config_path or environ.get("BESTROM_MCP_CONFIG")
    if user_path:
        user_file = Path(user_path).expanduser()
        if not user_file.is_file():
            raise ConfigError(f"config file not found: {user_file}")
        data = _merge(data, _load_toml(user_file))
        sources.append(str(user_file))

    env_overlay = _env_overlay(environ)
    if env_overlay:
        data = _merge(data, env_overlay)
        sources.append("environment")

    tree_raw = dict(data.get("tree", {}))
    root_raw = str(tree_raw.get("root") or "").strip()
    if not root_raw:
        root_raw = environ.get("BESTROM_TREE", "").strip()
    root = Path(root_raw).expanduser().resolve() if root_raw else _default_tree_root()
    if require_tree:
        problem = tree_root_problem(root)
        if problem:
            raise ConfigError(problem)

    tree = TreeCfg(
        root=root,
        out_dir=str(tree_raw.get("out_dir", TreeCfg.out_dir)),
        logs_dir=Path(str(tree_raw.get("logs_dir", TreeCfg.logs_dir))),
        dl_dir=Path(str(tree_raw.get("dl_dir", TreeCfg.dl_dir))),
        min_free_gb=_as_int(tree_raw.get("min_free_gb", TreeCfg.min_free_gb), "min_free_gb"),
    )

    b = dict(data.get("build", {}))
    build = BuildCfg(
        script=str(b.get("script", BuildCfg.script)),
        lunch=str(b.get("lunch", BuildCfg.lunch)),
        goal=str(b.get("goal", BuildCfg.goal)),
        jobs=_as_int(b.get("jobs", BuildCfg.jobs), "build.jobs"),
        official=_as_bool(b.get("official", BuildCfg.official)),
        unit_prefix=str(b.get("unit_prefix", BuildCfg.unit_prefix)),
        log_prefix=str(b.get("log_prefix", BuildCfg.log_prefix)),
        zip_glob=str(b.get("zip_glob", BuildCfg.zip_glob)),
    )

    v = dict(data.get("verify", {}))
    verify = VerifyCfg(
        profile=str(v.get("profile", VerifyCfg.profile)),
        profiles_dir=str(v.get("profiles_dir", VerifyCfg.profiles_dir)),
        marker_dir=Path(str(v.get("marker_dir", tree.logs_dir))),
    )

    d = dict(data.get("device", {}))
    device = DeviceCfg(
        adb_port=_as_int(d.get("adb_port", DeviceCfg.adb_port), "device.adb_port"),
        adb_host=str(d.get("adb_host", DeviceCfg.adb_host)),
        serial=str(d.get("serial", DeviceCfg.serial)),
        default_timeout_s=_as_int(
            d.get("default_timeout_s", DeviceCfg.default_timeout_s), "device.default_timeout_s"
        ),
        max_timeout_s=_as_int(
            d.get("max_timeout_s", DeviceCfg.max_timeout_s), "device.max_timeout_s"
        ),
        evidence_dir=Path(str(d.get("evidence_dir", tree.logs_dir / "crash-sweep"))),
        allow_remote_sideload=_as_bool(
            d.get("allow_remote_sideload", DeviceCfg.allow_remote_sideload)
        ),
    )

    a = dict(data.get("agent", {}))
    agent = AgentCfg(
        port=_as_int(a.get("port", AgentCfg.port), "agent.port"),
        socket=str(a.get("socket", AgentCfg.socket)),
        package=str(a.get("package", AgentCfg.package)),
        connect_timeout_s=_as_int(
            a.get("connect_timeout_s", AgentCfg.connect_timeout_s), "agent.connect_timeout_s"
        ),
        request_timeout_s=_as_int(
            a.get("request_timeout_s", AgentCfg.request_timeout_s), "agent.request_timeout_s"
        ),
        max_request_timeout_s=_as_int(
            a.get("max_request_timeout_s", AgentCfg.max_request_timeout_s),
            "agent.max_request_timeout_s",
        ),
        # Empty means "wherever device evidence goes", so the two never drift.
        evidence_dir=Path(str(a.get("evidence_dir") or device.evidence_dir)),
        evidence_subdir=str(a.get("evidence_subdir", AgentCfg.evidence_subdir)),
        state_file=str(a.get("state_file", AgentCfg.state_file)),
        inline_node_limit=_as_int(
            a.get("inline_node_limit", AgentCfg.inline_node_limit), "agent.inline_node_limit"
        ),
    )

    r = dict(data.get("release", {}))
    release = ReleaseCfg(
        chains=_as_list(r.get("chains", ReleaseCfg.chains)),
        sourceforge_project=str(r.get("sourceforge_project", ReleaseCfg.sourceforge_project)),
        sourceforge_frs_path=str(r.get("sourceforge_frs_path", ReleaseCfg.sourceforge_frs_path)),
        sourceforge_web_path=str(r.get("sourceforge_web_path", ReleaseCfg.sourceforge_web_path)),
        ota_repo=Path(str(r.get("ota_repo", tree.logs_dir / "bestrom_ota"))),
        ota_branch=str(r.get("ota_branch", ReleaseCfg.ota_branch)),
        site_repo=Path(str(r.get("site_repo", tree.logs_dir / "bestrom-project"))),
        pages_dir=Path(str(r.get("pages_dir", tree.logs_dir / "sf-release" / "pages"))),
        publish_timeout_s=_as_int(
            r.get("publish_timeout_s", ReleaseCfg.publish_timeout_s), "release.publish_timeout_s"
        ),
        kernel=str(r.get("kernel", ReleaseCfg.kernel)),
        base=str(r.get("base", ReleaseCfg.base)),
    )

    s = dict(data.get("safety", {}))
    extra_roots = [Path(p) for p in _as_list(s.get("allowlist_roots", ()))]
    roots: list[Path] = []
    for candidate in [tree.root, tree.logs_dir, tree.dl_dir, *extra_roots]:
        if candidate not in roots:
            roots.append(candidate)
    safety = SafetyCfg(
        allowlist_roots=tuple(roots),
        enable_publish=_as_bool(s.get("enable_publish", SafetyCfg.enable_publish)),
    )

    push_projects = _as_list(dict(data.get("push", {})).get("projects", ()))

    state_dir = Path(environ.get("BESTROM_MCP_STATE", str(SERVER_DIR / "state")))

    return Config(
        tree=tree,
        build=build,
        verify=verify,
        device=device,
        agent=agent,
        release=release,
        safety=safety,
        push_projects=push_projects,
        state_dir=state_dir,
        server_dir=SERVER_DIR,
        sources=tuple(sources),
    )


__all__ = [
    "CONFIRM_REQUIRED_TOOLS",
    "AgentCfg",
    "Config",
    "ConfigError",
    "PathNotAllowed",
    "SERVER_DIR",
    "load_config",
    "tree_root_problem",
    "replace",
]
