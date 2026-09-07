"""Config precedence, tree-root discovery and the path allowlist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bestrom_mcp.config import (
    CONFIRM_REQUIRED_TOOLS,
    SERVER_DIR,
    ConfigError,
    PathNotAllowed,
    load_config,
    tree_root_problem,
)

SECRET_KEYS = ("token", "password", "secret", "key", "authorization", "extraheader", "credential")


def test_shipped_config_loads() -> None:
    cfg = load_config(environ={})
    assert cfg.build.lunch == "bestrom_peridot-cp2a-user"
    assert cfg.build.goal == "bestrom"
    assert cfg.device.adb_port == 15038
    assert cfg.device.allow_remote_sideload is False
    assert str(SERVER_DIR) in cfg.sources[1]


def test_tree_root_is_derived_structurally() -> None:
    """vendor/bestrom/tools/mcp -> four levels up, nothing hardcoded."""
    cfg = load_config(environ={})
    assert cfg.tree.root == SERVER_DIR.parents[3]
    assert (cfg.tree.root / "vendor" / "bestrom").is_dir()


def test_bestrom_tree_env_overrides_the_root(tmp_path: Path) -> None:
    cfg = load_config(environ={"BESTROM_TREE": str(tmp_path)})
    assert cfg.tree.root == tmp_path.resolve()


def test_env_override_beats_the_toml() -> None:
    cfg = load_config(
        environ={
            "BESTROM_MCP_DEVICE_ADB_PORT": "15999",
            "BESTROM_MCP_BUILD_JOBS": "8",
            "BESTROM_MCP_SAFETY_ENABLE_PUBLISH": "false",
        }
    )
    assert cfg.device.adb_port == 15999
    assert cfg.build.jobs == 8
    assert cfg.safety.enable_publish is False
    assert "environment" in cfg.sources


def test_user_toml_beats_the_shipped_one(tmp_path: Path) -> None:
    user = tmp_path / "user.toml"
    user.write_text('[device]\nserial = "deadbeef"\n', encoding="utf-8")
    cfg = load_config(environ={"BESTROM_MCP_CONFIG": str(user)})
    assert cfg.device.serial == "deadbeef"
    assert cfg.device.adb_port == 15038  # still from the shipped file


def test_missing_user_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"BESTROM_MCP_CONFIG": str(tmp_path / "nope.toml")})


def test_bad_integer_is_an_error() -> None:
    with pytest.raises(ConfigError):
        load_config(environ={"BESTROM_MCP_BUILD_JOBS": "sixty-four"})


# -- allowlist -----------------------------------------------------------


def test_allowlist_accepts_a_path_inside_the_tree() -> None:
    cfg = load_config(environ={})
    resolved = cfg.resolve_allowed("vendor/bestrom/CHANGELOG.md")
    assert resolved == cfg.tree.root / "vendor" / "bestrom" / "CHANGELOG.md"


def test_allowlist_accepts_the_logs_dir() -> None:
    cfg = load_config(environ={})
    assert cfg.resolve_allowed(cfg.tree.logs_dir / "build-x.log")


def test_allowlist_rejects_dotdot_escape() -> None:
    cfg = load_config(environ={})
    with pytest.raises(PathNotAllowed):
        cfg.resolve_allowed("../../../../etc/passwd")


def test_allowlist_rejects_an_absolute_path_outside_the_roots() -> None:
    cfg = load_config(environ={})
    with pytest.raises(PathNotAllowed):
        cfg.resolve_allowed("/etc/shadow")


def test_allowlist_resolves_symlinks_before_checking(tmp_path: Path) -> None:
    """A symlink inside the tree pointing outside it must not slip through."""
    cfg = load_config(environ={"BESTROM_TREE": str(tmp_path)})
    outside = tmp_path.parent / "outside-the-tree.txt"
    outside.write_text("x", encoding="utf-8")
    link = tmp_path / "sneaky"
    link.symlink_to(outside)
    with pytest.raises(PathNotAllowed):
        cfg.resolve_allowed(link)


def test_must_exist_is_enforced() -> None:
    cfg = load_config(environ={})
    with pytest.raises(PathNotAllowed):
        cfg.resolve_allowed("vendor/bestrom/no-such-file", must_exist=True)


# -- the config resource -------------------------------------------------


def test_effective_config_has_no_secret_shaped_keys() -> None:
    cfg = load_config(environ={})
    text = json.dumps(cfg.redacted_dict()).lower()
    for banned in SECRET_KEYS:
        assert f'"{banned}"' not in text, banned


def test_effective_config_reports_what_is_enabled() -> None:
    cfg = load_config(environ={})
    data = cfg.redacted_dict()
    assert data["safety"]["destructive_enabled"]["device_sideload"] is False
    assert data["verify"]["profile"] == "peridot"
    assert data["config_sources"][0] == "defaults"


# -- the tree-root guard -------------------------------------------------


def test_a_root_that_is_not_a_tree_is_rejected_at_startup(tmp_path: Path) -> None:
    """A client that leaks an unexpanded ${VAR} into BESTROM_TREE used to start
    the server happily and fail on the fifth tool call with an unrelated
    message about the allowlist."""
    with pytest.raises(ConfigError, match="BESTROM_TREE"):
        load_config(environ={"BESTROM_TREE": str(tmp_path)}, require_tree=True)


def test_a_real_tree_passes_the_guard(tmp_path: Path) -> None:
    (tmp_path / "vendor" / "bestrom").mkdir(parents=True)
    cfg = load_config(environ={"BESTROM_TREE": str(tmp_path)}, require_tree=True)
    assert cfg.tree.root == tmp_path.resolve()


def test_the_shipped_tree_passes_the_guard() -> None:
    assert tree_root_problem(SERVER_DIR.parents[3]) == ""


def test_the_config_resource_reports_only_real_controls() -> None:
    """require_confirm was configurable and read by nothing. What is published
    now is a description of the code, and it has to match it."""
    data = load_config(environ={}).redacted_dict()
    assert data["safety"]["confirm_required"] == list(CONFIRM_REQUIRED_TOOLS)
    assert "require_confirm" not in data["safety"]
