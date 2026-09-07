"""Device-side argument construction.

Everything here becomes a string the phone's sh parses. Python's repr is not a
shell quoter and re.match's "$" also matches before a trailing newline, so both
are pinned.
"""

from __future__ import annotations

from bestrom_mcp.ops.device import (
    DEVICE_PROPS,
    PACKAGE_RE,
    _parse_props,
    _props_command,
    _root_shell,
)


class FakeShell:
    """Captures the command string instead of talking to a device."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, cfg, command, timeout=None):
        self.seen.append(command)

        class R:
            out = ""
            err = ""
            truncated = False
            timed_out = False
            rc = 0

        return R()


def test_root_commands_are_shell_quoted(monkeypatch) -> None:
    import bestrom_mcp.ops.device as device

    shell = FakeShell()
    monkeypatch.setattr(device, "_shell", shell)
    tricky = """logcat -d | sed -E 's/x"y/z/' | grep 'a\\\\b'"""
    device._root_shell(None, tricky, True)
    sent = shell.seen[0]
    assert sent.startswith("su -c ")
    # Round-trip through a POSIX lexer: what the phone's sh sees must be the
    # command we asked for, byte for byte.
    import shlex

    assert shlex.split(sent)[2] == tricky


def test_a_non_root_command_is_passed_through(monkeypatch) -> None:
    import bestrom_mcp.ops.device as device

    shell = FakeShell()
    monkeypatch.setattr(device, "_shell", shell)
    device._root_shell(None, "uptime", False)
    assert shell.seen == ["uptime"]


def test_package_regex_rejects_a_trailing_newline() -> None:
    assert PACKAGE_RE.fullmatch("com.android.camera")
    assert not PACKAGE_RE.fullmatch("com.android.camera\n")
    assert not PACKAGE_RE.fullmatch("com.foo; rm -rf /")
    assert not PACKAGE_RE.fullmatch("-com.foo")


def test_props_are_parsed_by_key_not_by_position() -> None:
    """A missing property prints an empty value; nothing after it shifts."""
    out = "\n".join(
        [
            "ro.build.version.incremental=20260907",
            "ro.bestrom.version=",
            "ro.bestrom.build.status=",
            "ro.build.fingerprint=Xiaomi/peridot/peridot:17/x",
            "selinux=Enforcing",
            "uptime= 10:00:00 up 2 days",
        ]
    )
    parsed = _parse_props(out)
    assert parsed["ro.bestrom.version"] == ""
    assert parsed["ro.build.fingerprint"] == "Xiaomi/peridot/peridot:17/x"
    assert parsed["selinux"] == "Enforcing"


def test_the_props_command_asks_for_key_equals_value() -> None:
    command = _props_command()
    for name in DEVICE_PROPS:
        assert name in command
    assert '"$p=$(getprop $p)"' in command
    assert '"selinux=$(getenforce)"' in command
