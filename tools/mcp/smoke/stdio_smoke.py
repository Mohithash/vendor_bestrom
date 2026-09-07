#!/usr/bin/env python3
"""End-to-end smoke test of the BestROM MCP server over stdio.

Spawns the server as a client would and keeps stdin OPEN for the whole
exchange. Piping a few lines in with printf closes stdin, the server sees EOF
and exits after the first response, and the run looks like a protocol failure
when it is really a test harness bug — that is how this was mis-tested before.

It runs nothing destructive: no build, no push, no upload, no flash. Every
mutating tool is exercised with dry_run=true, and device_sideload and
release_publish are asserted to REFUSE without confirm.

The checks that need a completed build (build_artifacts, verify_image,
release_prepare) are skipped when out/target/product/peridot does not exist, so
this is also the right first command on a fresh clone.

    .venv/bin/python smoke/stdio_smoke.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER_DIR = HERE.parent
PROTOCOL = "2025-06-18"

failures: list[str] = []
skipped: list[str] = []
checks = 0

TREE = SERVER_DIR.parents[3]
OUT = TREE / "out" / "target" / "product" / "peridot"
HAVE_OUT = OUT.is_dir()


def check(condition: bool, label: str) -> bool:
    global checks
    checks += 1
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        failures.append(label)
    return bool(condition)


def skip(label: str, why: str) -> None:
    print(f"  skip {label} ({why})")
    skipped.append(label)


class Client:
    """A minimal newline-framed JSON-RPC client over the server's stdio."""

    def __init__(self, stderr_path: Path) -> None:
        env = dict(os.environ)
        env.setdefault("BESTROM_TREE", str(SERVER_DIR.parents[3]))
        self.stderr_file = stderr_path.open("wb")
        self.proc = subprocess.Popen(
            [str(SERVER_DIR / ".venv" / "bin" / "bestrom-mcp"), "--transport", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_file,
            cwd=str(SERVER_DIR),
            env=env,
            text=True,
            bufsize=1,
        )
        self._id = 0

    def send(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        message: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self._id += 1
            message["id"] = self._id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        return self._read(message["id"])

    def _read(self, want_id: int, timeout: float = 180.0) -> dict:
        deadline = time.time() + timeout
        assert self.proc.stdout is not None
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout (did it crash? see the stderr log)")
            line = line.strip()
            if not line:
                continue
            # Any non-JSON byte on stdout would corrupt the stream; a decode
            # error here IS the assertion that the server keeps stdout clean.
            payload = json.loads(line)
            if payload.get("id") == want_id:
                return payload
        raise TimeoutError(f"no response to id {want_id} within {timeout}s")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=15)
        except (subprocess.TimeoutExpired, OSError):
            self.proc.kill()
        finally:
            self.stderr_file.close()


def call(client: Client, name: str, arguments: dict | None = None) -> dict:
    response = client.send("tools/call", {"name": name, "arguments": arguments or {}})
    return response.get("result", response)


def structured(result: dict) -> dict:
    return result.get("structuredContent") or {}


def handshake(client: Client) -> dict:
    response = client.send(
        "initialize",
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "bestrom-smoke", "version": "1.0"},
        },
    )
    client.send("notifications/initialized", {}, notify=True)
    return response.get("result", {})


def tool_names(client: Client) -> list[str]:
    return [t["name"] for t in client.send("tools/list", {})["result"]["tools"]]


def main() -> int:
    stderr_path = SERVER_DIR / "state" / "smoke-stderr.log"
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    print("== initialize ==")
    client = Client(stderr_path)
    try:
        info = handshake(client)
        print(f"  server: {info.get('serverInfo')}  protocol: {info.get('protocolVersion')}")
        check(info.get("protocolVersion") is not None, "initialize returned a protocol version")
        check("tools" in info.get("capabilities", {}), "server advertises tools")
        check("resources" in info.get("capabilities", {}), "server advertises resources")
        check("prompts" in info.get("capabilities", {}), "server advertises prompts")

        print("\n== tools/list ==")
        tools = client.send("tools/list", {})["result"]["tools"]
        for tool in tools:
            ann = tool.get("annotations") or {}
            flags = "".join(
                letter
                for letter, key in (
                    ("R", "readOnlyHint"),
                    ("D", "destructiveHint"),
                    ("I", "idempotentHint"),
                    ("O", "openWorldHint"),
                )
                if ann.get(key)
            )
            print(f"  {tool['name']:22s} [{flags:4s}] {ann.get('title', '')}")
        check(len(tools) == 19, f"19 tools registered (got {len(tools)})")
        check(all(t.get("annotations", {}).get("title") for t in tools), "every tool has a title")
        check(all(t.get("outputSchema") for t in tools), "every tool has an outputSchema")
        check(
            all("readOnlyHint" in (t.get("annotations") or {}) for t in tools),
            "every tool carries annotations",
        )

        print("\n== resources/list ==")
        resources = client.send("resources/list", {})["result"]["resources"]
        for resource in resources:
            print(f"  {resource['uri']:34s} {resource.get('mimeType', '')}")
        check(len(resources) == 6, f"6 resources registered (got {len(resources)})")

        print("\n== prompts/list ==")
        prompt_list = client.send("prompts/list", {})["result"]["prompts"]
        for prompt in prompt_list:
            print(f"  {prompt['name']}")
        check(len(prompt_list) == 4, f"4 prompts registered (got {len(prompt_list)})")

        print("\n== resources/read bestrom://style-guide ==")
        read = client.send("resources/read", {"uri": "bestrom://style-guide"})["result"]
        body = read["contents"][0]["text"]
        print("  " + body.splitlines()[0])
        check("Sentence-case summary" in body, "style guide names the subject form")

        print("\n== env_check ==")
        result = call(client, "env_check")
        data = structured(result)
        print(
            f"  tree={data.get('tree')} cores={data.get('cores')} "
            f"free={data.get('disk_free_gb')}G out={data.get('out_size_gb')}G "
            f"headroom_ok={data.get('headroom_ok')} systemd={data.get('systemd_user_ok')} "
            f"in_flight={(data.get('build_in_flight') or {}).get('running')} "
            f"adb_listener={data.get('adb_port_listener')}"
        )
        for blocker in data.get("blockers", []):
            print(f"    blocker: {blocker}")
        check(not result.get("isError"), "env_check returned without error")
        check(bool(data), "env_check returned structuredContent")
        check(data.get("envsetup_present") is True, "build/envsetup.sh is present")

        print("\n== repo_status ==")
        result = call(client, "repo_status", {"include_dirty_scan": False})
        data = structured(result)
        for project in data.get("projects", []):
            print(
                f"  {project['path']:32s} {project['branch']:24s} "
                f"manifest={project['manifest_revision']:16s} "
                f"dirty={project['dirty_files']} match={project['branch_matches_manifest']}"
            )
        for mismatch in data.get("mismatches", []):
            print(f"    mismatch: {mismatch}")
        check(not result.get("isError"), "repo_status returned without error")
        check(bool(data.get("projects")), "repo_status listed projects")

        print("\n== manifest_check ==")
        result = call(client, "manifest_check")
        data = structured(result)
        print(f"  mirror_identical={data.get('mirror_identical')} ok={data.get('ok')}")
        for entry in data.get("copyfiles", []):
            print(
                f"    {entry['src']} -> {entry['dest']}  present={entry['present']} "
                f"root_copy_matches={entry['root_copy_matches']} {entry['detail']}"
            )
        check(not result.get("isError"), "manifest_check returned without error")

        print("\n== build_artifacts ==")
        if not HAVE_OUT:
            skip("build_artifacts", f"no {OUT}; needs a completed build")
        else:
            result = call(client, "build_artifacts", {"compute_sha256": False})
            data = structured(result)
            zip_info = data.get("zip") or {}
            print(f"  zip={zip_info.get('name')} size={zip_info.get('size')} ({zip_info.get('size_gb')} GB)")
            print(f"  props={data.get('build_props')}")
            print(f"  previous={data.get('previous_release')}")
            check(not result.get("isError"), "build_artifacts returned without error")

        print("\n== verify_image (no marker write) ==")
        result = call(client, "verify_image", {"write_marker": False})
        data = structured(result)
        for entry in data.get("checks", []):
            state = "ok  " if entry["passed"] else "FAIL"
            print(
                f"  {state} {entry['id']:34s} {entry['kind']:22s} "
                f"expected {entry['op']} {entry['expected']} got {entry['actual']}"
            )
        print(f"  passed={data.get('passed')} failed_ids={data.get('failed_ids')}")
        print(f"  marker_line={data.get('marker_line')!r} marker_path={data.get('marker_path')!r}")
        check(not result.get("isError"), "verify_image returned without error")
        check(data.get("marker_path") == "", "verify_image wrote no marker when not asked to")
        if not data.get("passed"):
            check(data.get("marker_line") == "", "marker_line is empty when a check failed")

        print("\n== verify_image (subset asks for the marker) ==")
        data = structured(
            call(client, "verify_image", {"checks": ["zip-size-sane"], "write_marker": True})
        )
        print(f"  partial={data.get('partial')} checks_run={data.get('checks_run')}")
        print(f"  note={data.get('note')}")
        check(data.get("partial") is True, "a subset run is reported as partial")
        check(
            data.get("marker_path") == "" and data.get("marker_line") == "",
            "a subset run cannot write the gate marker",
        )

        print("\n== device_list ==")
        result = call(client, "device_list")
        data = structured(result)
        print(
            f"  port={data.get('port')} listener={data.get('listener_present')} "
            f"devices={data.get('devices')}"
        )
        if data.get("unreachable_reason"):
            print(f"  unreachable: {data['unreachable_reason']}")
        check(not result.get("isError"), "device_list returned without error")
        check(
            data.get("listener_present") is True or "adb was NOT run" in (data.get("unreachable_reason") or ""),
            "device_list refused to run adb with no listener",
        )

        print("\n== commit_message_check (good) ==")
        good = (
            "vendor: Add the BestROM MCP server\n"
            "\n"
            "Wraps the build, verify, device and release chains as MCP tools so\n"
            "an agent can drive them without ad-hoc shell.\n"
        )
        data = structured(call(client, "commit_message_check", {"text": good}))
        print(f"  ok={data.get('ok')} area={data.get('area')} violations={data.get('violations')}")
        check(data.get("ok") is True, "a well-formed message passes")

        print("\n== commit_message_check (bad) ==")
        bad = "Fixed stuff. \U0001F680\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"
        data = structured(call(client, "commit_message_check", {"text": bad}))
        rules = [v["rule_id"] for v in data.get("violations", [])]
        print(f"  ok={data.get('ok')} rules={rules}")
        print("  suggested: " + repr(data.get("suggested_message")))
        check(data.get("ok") is False, "a bad message fails")
        check("ai-trailer" in rules, "the Claude trailer is flagged")
        check("emoji" in rules, "the emoji is flagged")

        print("\n== build_start (dry run) ==")
        data = structured(call(client, "build_start", {"dry_run": True, "log_name": "smoke"}))
        print(f"  job_id={data.get('job_id')}")
        print(f"  log={data.get('log_path')}")
        print(f"  command: {data.get('command_preview')}")
        if data.get("refused_reason"):
            print(f"  refused: {data['refused_reason']}")
        check(
            "build-bestrom-run.sh" in (data.get("command_preview") or "")
            or bool(data.get("refused_reason")),
            "build_start dry run returned the real command (or refused for a stated reason)",
        )

        print("\n== release_prepare (dry run) ==")
        data = structured(
            call(
                client,
                "release_prepare",
                {"notes": "Smoke test\n  * nothing was published.", "dry_run": True},
            )
        )
        if data.get("refused_reason"):
            print(f"  refused: {data['refused_reason']}")
        else:
            print(f"  version={data.get('version')}")
            print("  readme first line: " + (data.get("readme_txt") or "").splitlines()[0])
            print(f"  gate={data.get('gate')}")
            print(f"  warnings={data.get('warnings')}")
        check(not data.get("written_paths"), "release_prepare wrote nothing on a dry run")

        print("\n== release_prepare (notes_path outside the notes location) ==")
        data = structured(
            call(
                client,
                "release_prepare",
                {"notes_path": str(SERVER_DIR / "bestrom.toml"), "dry_run": True},
            )
        )
        print(f"  refused: {data.get('refused_reason')}")
        check(bool(data.get("refused_reason")), "release_prepare refuses an arbitrary file read")
        check(not data.get("readme_txt"), "no content from the refused file came back")

        print("\n== changelog_add (dry run) ==")
        data = structured(
            call(
                client,
                "changelog_add",
                {"section": "Smoke", "bullets": ["Nothing was written."], "dry_run": True},
            )
        )
        print("  diff:\n" + "\n".join("    " + line for line in (data.get("diff") or "").splitlines()))
        check(data.get("dry_run") is True, "changelog_add stayed in dry run")

        print("\n== refusals ==")
        data = structured(call(client, "device_sideload", {"dry_run": True}))
        print(f"  device_sideload: {data.get('refused_reason')}")
        check(bool(data.get("refused_reason")), "device_sideload refuses by default")
        check(bool(data.get("local_commands")), "device_sideload still returns the local command")

        data = structured(call(client, "device_sideload", {"images": ["boot"], "dry_run": True}))
        print(f"  device_sideload boot only: {data.get('refused_reason')}")
        check(
            "vendor_boot" in (data.get("refused_reason") or ""),
            "device_sideload refuses boot without vendor_boot",
        )

        data = structured(call(client, "release_publish", {"chain": "hardening", "dry_run": False}))
        print(f"  release_publish: {data.get('refused_reason')}")
        check(bool(data.get("refused_reason")), "release_publish refuses without confirm")

        data = structured(call(client, "release_publish", {"chain": "wildcat"}))
        print(f"  release_publish unknown chain: {data.get('refused_reason')}")
        check("unknown chain" in (data.get("refused_reason") or ""), "unknown chain refused")

        data = structured(call(client, "build_cancel", {"job_id": "bestrom-build-nope"}))
        print(f"  build_cancel: {data.get('refused_reason')}")
        check(bool(data.get("refused_reason")), "build_cancel refuses an unknown job")

        data = structured(call(client, "repo_sync", {"dry_run": False, "confirm": False}))
        print(f"  repo_sync: {data.get('refused_reason')}")
        check("confirm=true" in (data.get("refused_reason") or ""), "repo_sync refuses without confirm")

        data = structured(
            call(client, "repo_sync", {"projects": ["--force-remove-dirty"], "dry_run": True})
        )
        print(f"  repo_sync option-shaped project: {data.get('refused_reason')}")
        check(
            "looks like an option" in (data.get("refused_reason") or ""),
            "repo_sync refuses an option-shaped project",
        )
        check(
            "--force-remove-dirty" not in (data.get("command_preview") or ""),
            "the refused string never reached the command preview",
        )

        print("\n== determinism ==")
        first = tool_names(client)
        second_client = Client(SERVER_DIR / "state" / "smoke-stderr-2.log")
        try:
            handshake(second_client)
            second = tool_names(second_client)
        finally:
            second_client.close()
        check(first == second, "tools/list order is identical across two server runs")

    finally:
        client.close()

    size = stderr_path.stat().st_size if stderr_path.is_file() else 0
    print(f"\nserver stderr captured to {stderr_path} ({size} bytes)")
    if skipped:
        print(f"{len(skipped)} skipped (no build output yet): " + ", ".join(skipped))
    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        for failure in failures:
            print(f"  FAILED: {failure}")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
