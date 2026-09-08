"""Secrets in, nothing recoverable out — and ordinary build output unmangled."""

from __future__ import annotations

import pytest

from bestrom_mcp.redact import MASK, scrub, scrub_any

SECRETS = [
    (
        "http.extraheader=AUTHORIZATION: basic eHktdG9rZW46Z2hwX0FBQUFBQUFBQUFBQUFBQUE=",
        "eHktdG9rZW4",
    ),
    ("Authorization: Bearer ghp_0123456789abcdefghijABCDEFGHIJ0123", "ghp_0123456789"),
    ("token ghp_0123456789abcdefghijABCDEFGHIJ0123 leaked", "ghp_0123456789"),
    ("github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz012345", "github_pat_11ABCDEFG0"),
    ("remote: https://x-access-token:ghs_abcdefghijklmnopqrst@github.com/x/y", "ghs_abcdefghij"),
    ("cloning https://mohithash:hunter2hunter2@github.com/x/y.git", "hunter2hunter2"),
    ("GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789", "ghp_abcdefghij"),
    ("password: correct-horse-battery-staple", "correct-horse"),
    ("Load key /home/sal/.ssh/id_ed25519_sourceforge: bad permissions", "id_ed25519_sourceforge"),
    (
        "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----",
        "b3BlbnNzaC1rZXk",
    ),
    (
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabcdefghijklmnopqrstuvwxyz0123456789 sal@serverhive1",
        "AAAAC3NzaC1lZDI1NTE5",
    ),
    ("pairing code: 481920", "481920"),
    ('{"code": "481920", "client": "bestrom-mcp"}', "481920"),
    ("agent.pair code=481920 refused", "481920"),
]


@pytest.mark.parametrize("text,leak", SECRETS, ids=[s[0][:28] for s in SECRETS])
def test_secret_is_masked(text: str, leak: str) -> None:
    out = scrub(text)
    assert leak not in out, out
    assert MASK in out


CLEAN = [
    "[ 99% 4321/4321] Package OTA: out/target/product/peridot/BestROM-3.0.zip",
    "FAILED: out/soong/.intermediates/frameworks/base/foo/bar.jar",
    "frameworks/base/core/java/android/Foo.java:42: error: cannot find symbol",
    "=== 2026-09-07T10:29:50Z BUILD EXIT: 0 ===",
    "ro.build.fingerprint=BestROM/peridot/peridot:17/BP1A/1010:user/release-keys",
    "  87654321  /system/priv-app/MiuiCamera/MiuiCamera.apk",
    "avc: denied { read } for comm=\"camerahalserver\" scontext=u:r:hal_camera_default:s0",
    # The pairing-code rule is six digits next to the word, and nothing else: a
    # bare \\d{6} would eat build numbers, byte counts and error codes.
    "Total 123456 objects, 654321 deltas",
    "the function failed: code=1000 category=DENIED",
    "the bridge answered error code -32012 to request 2",
]


@pytest.mark.parametrize("text", CLEAN, ids=[c[:30] for c in CLEAN])
def test_ordinary_output_is_not_mangled(text: str) -> None:
    assert scrub(text) == text


def test_scrub_any_walks_containers() -> None:
    payload = {
        "log": ["ok", "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz01"],
        "nested": {"cmd": ("git", "push", "https://u:ghp_abcdefghijklmnopqrstuvwxyz01@github.com")},
        "count": 3,
    }
    out = scrub_any(payload)
    assert "ghp_abcdefghij" not in str(out)
    assert out["count"] == 3
    assert out["log"][0] == "ok"


def test_empty_and_none_survive() -> None:
    assert scrub("") == ""
    assert scrub_any(None) is None
    assert scrub_any(7) == 7
