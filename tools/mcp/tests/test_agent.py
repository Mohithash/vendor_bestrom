"""The Agent mode bridge client, against a fake bridge on a real socket.

No device and no adb: ``proc.run`` is patched to a recorder that fails the test
if anything but ``adb forward`` is attempted, and the bridge is a TCP server in
a thread speaking the same newline-delimited JSON-RPC the phone speaks. That
covers the parts a device cannot: the framing across recv boundaries, the
confirm floor, the error mapping, and the rule that the pairing secret never
appears in anything a tool returns.
"""

from __future__ import annotations

import json
import socket
import stat
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from bestrom_mcp import proc
from bestrom_mcp.config import CONFIRM_REQUIRED_TOOLS, load_config
from bestrom_mcp.ops import agent as agent_ops

SECRET = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-aBcDe"  # 43 chars, base64url
CODE = "123456"

TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


# -- the fake bridge ----------------------------------------------------


class FakeBridge:
    """A TCP server that answers one NDJSON request per line.

    ``handlers`` maps a method name to a callable returning either
    ``{"result": ...}`` or ``{"error": {...}}``. ``chunks`` splits every reply
    into that many pieces, one of which lands inside a multi-byte UTF-8
    sequence, so the client's reassembly is exercised rather than assumed.
    """

    def __init__(self, handlers: dict, chunks: int = 1) -> None:
        self.handlers = handlers
        self.chunks = chunks
        self.seen: list[dict] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.stopped = False
        self.thread.start()

    def _serve(self) -> None:
        while not self.stopped:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    self._session(conn)
                except OSError:
                    pass

    def _session(self, conn: socket.socket) -> None:
        buffer = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                request = json.loads(line.decode("utf-8"))
                self.seen.append(request)
                handler = self.handlers.get(request["method"])
                if handler is None:
                    body = {"error": {"code": -32601, "message": "no such method"}}
                else:
                    body = handler(request.get("params") or {})
                payload = {"jsonrpc": "2.0", "id": request.get("id")}
                payload.update(body)
                self._write(conn, json.dumps(payload).encode("utf-8") + b"\n")

    def _write(self, conn: socket.socket, data: bytes) -> None:
        if self.chunks <= 1:
            conn.sendall(data)
            return
        step = max(1, len(data) // self.chunks)
        for start in range(0, len(data), step):
            conn.sendall(data[start : start + step])

    def close(self) -> None:
        self.stopped = True
        try:
            self.sock.close()
        except OSError:
            pass


def _auth_ok(params):
    return {"result": {"ok": True}} if params.get("token") == SECRET else _err(-32001, "no session")


def _err(code: int, message: str, data: dict | None = None):
    body = {"code": code, "message": message}
    if data:
        body["data"] = data
    return {"error": body}


HELLO = {
    "protocol": 1,
    "app_version": "1.0",
    "device": {"model": "POCO F6", "device": "peridot", "sdk": 37, "fingerprint": "x", "bestrom_version": "3.0"},
    "capabilities": ["ui.tree", "ui.tap", "agent.stop"],
    "state": {"paired": False, "a11y_connected": True, "keyguard_locked": False,
              "rate_limit_per_s": 10, "idle_timeout_s": 1800, "audit_capacity": 500},
}


def base_handlers() -> dict:
    return {
        "agent.hello": lambda p: {"result": dict(HELLO)},
        "agent.auth": _auth_ok,
        "agent.pair": (
            lambda p: {"result": {"token": SECRET, "code_expires_utc": "2026-09-08T12:00:00Z",
                                  "capabilities": HELLO["capabilities"]}}
            if p.get("code") == CODE
            else _err(-32002, "bad code")
        ),
        "ui.tap": lambda p: {"result": {"ok": True, "method": "node", "target": "id/ok"}},
        "ui.type": lambda p: {"result": {"ok": True, "chars": len(p.get("text", ""))}},
        "log.list": lambda p: {"result": {"entries": [], "total": 0, "capacity": 500}},
    }


# -- the harness --------------------------------------------------------


class AdbRecorder:
    """Stands in for proc.run. Anything that is not `adb forward` is a failure."""

    def __init__(self) -> None:
        self.argvs: list[tuple[str, ...]] = []

    def __call__(self, argv, **kwargs):
        argv = tuple(str(a) for a in argv)
        self.argvs.append(argv)
        assert argv[0] == "adb" and "forward" in argv, f"unexpected command: {argv}"
        return proc.ProcResult(argv, 0, "", "")

    @property
    def forwards(self) -> list[tuple[str, ...]]:
        return [a for a in self.argvs if "--remove" not in a]

    @property
    def removes(self) -> list[tuple[str, ...]]:
        return [a for a in self.argvs if "--remove" in a]


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    """A config pointing at a fake bridge, with adb and the port guard patched."""
    bridge = FakeBridge(base_handlers())
    cfg = load_config(environ={})
    cfg = replace(
        cfg,
        state_dir=tmp_path / "state",
        agent=replace(cfg.agent, port=bridge.port, evidence_dir=tmp_path / "evidence"),
    )
    recorder = AdbRecorder()
    monkeypatch.setattr("bestrom_mcp.ops.device.proc.run", recorder)
    monkeypatch.setattr("bestrom_mcp.ops.device.port_listener", lambda port: (True, "sshd"))
    yield cfg, bridge, recorder
    bridge.close()


def pair(cfg) -> None:
    agent_ops.write_secret(cfg, SECRET)


# -- the port guard -----------------------------------------------------


def test_nothing_runs_adb_without_a_listener(env, monkeypatch) -> None:
    """adb -P on an unbound port squats the tunnel. Every tool refuses first."""
    cfg, _bridge, recorder = env
    pair(cfg)
    monkeypatch.setattr("bestrom_mcp.ops.device.port_listener", lambda port: (False, ""))
    monkeypatch.setattr(
        "bestrom_mcp.ops.device.proc.run",
        lambda *a, **k: pytest.fail("adb ran with no listener on the port"),
    )
    for result in (
        agent_ops.agent_status(cfg),
        agent_ops.agent_functions(cfg),
        agent_ops.agent_ui_tree(cfg),
        agent_ops.agent_apps(cfg),
        agent_ops.agent_log(cfg),
        agent_ops.agent_tap(cfg, x=1, y=1, dry_run=False, confirm=True),
    ):
        assert "listening" in result.refused_reason, result.refused_reason
    assert recorder.argvs == []


# -- the forward --------------------------------------------------------


def test_the_forward_argv_is_exact_and_is_taken_down(env) -> None:
    cfg, _bridge, recorder = env
    pair(cfg)
    agent_ops.agent_log(cfg, limit=5)
    assert recorder.forwards == [
        (
            "adb", "-P", "15038", "-s", "bc94484f", "forward",
            f"tcp:{cfg.agent.port}", "localabstract:bestrom_agent",
        )
    ]
    # Left open, tcp:8765 on this machine is a door to the phone for every
    # local process, so the call that opened it closes it.
    assert recorder.removes == [
        ("adb", "-P", "15038", "-s", "bc94484f", "forward", "--remove", f"tcp:{cfg.agent.port}")
    ]


def test_a_failed_forward_is_a_refusal_not_an_exception(env, monkeypatch) -> None:
    cfg, _bridge, _recorder = env
    pair(cfg)
    monkeypatch.setattr(
        "bestrom_mcp.ops.device.proc.run",
        lambda argv, **k: proc.ProcResult(tuple(argv), 1, "", "device unauthorized"),
    )
    result = agent_ops.agent_status(cfg)
    assert "adb forward failed" in result.refused_reason
    assert "forward --remove" in result.refused_reason


# -- framing ------------------------------------------------------------


def test_a_reply_split_across_recv_boundaries_is_reassembled(tmp_path, monkeypatch) -> None:
    """Including a split inside a multi-byte character and an escaped newline."""
    title = "Wi‑Fi ▸ Erweitert\nzweite Zeile"
    handlers = base_handlers()
    handlers["ui.tree"] = lambda p: {
        "result": {
            "tree_id": "abc123",
            "window": {"package": "com.android.settings", "title": title, "bounds": [0, 0, 1220, 2712]},
            "nodes": [{"id": 0, "cls": "TextView", "text": title}],
            "node_count": 1,
            "truncated": False,
        }
    }
    bridge = FakeBridge(handlers, chunks=7)
    cfg = replace(
        load_config(environ={}),
        state_dir=tmp_path / "state",
        agent=replace(load_config(environ={}).agent, port=bridge.port, evidence_dir=tmp_path / "e"),
    )
    monkeypatch.setattr("bestrom_mcp.ops.device.proc.run", AdbRecorder())
    monkeypatch.setattr("bestrom_mcp.ops.device.port_listener", lambda port: (True, "sshd"))
    agent_ops.write_secret(cfg, SECRET)
    try:
        tree = agent_ops.agent_ui_tree(cfg)
    finally:
        bridge.close()
    assert tree.refused_reason == ""
    assert tree.window.title == title
    assert tree.nodes[0]["text"] == title


def test_an_oversized_request_is_refused_before_it_is_sent(env) -> None:
    cfg, _bridge, _recorder = env
    pair(cfg)
    with pytest.raises(ValueError, match="caps a request line"):
        agent_ops._encode({"params": {"blob": "x" * (agent_ops.MAX_REQUEST_BYTES + 10)}})


# -- pairing and the secret ---------------------------------------------


def test_pairing_stores_the_secret_0600_and_returns_none_of_it(env) -> None:
    cfg, _bridge, _recorder = env
    result = agent_ops.agent_pair(cfg, code=CODE)
    assert result.paired is True
    path = agent_ops.state_path(cfg)
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert SECRET in path.read_text(encoding="utf-8")
    dumped = result.model_dump_json()
    assert SECRET not in dumped
    assert "token" not in dumped.lower()


def test_a_wrong_code_is_refused_and_stores_nothing(env) -> None:
    cfg, _bridge, _recorder = env
    result = agent_ops.agent_pair(cfg, code="000000")
    assert result.paired is False
    assert "BAD_PAIRING_CODE" in result.refused_reason
    assert not agent_ops.state_path(cfg).exists()


def test_no_pair_field_can_carry_the_code_back(env) -> None:
    """The six digits are as good as the secret while the code is live."""
    cfg, bridge, _recorder = env
    bridge.handlers["agent.pair"] = lambda p: {
        "result": {
            "token": SECRET,
            "code_expires_utc": "2026-09-08T12:00:00Z",
            "capabilities": ["ui.tree"],
        }
    }
    result = agent_ops.agent_pair(cfg, code=CODE)
    assert CODE not in result.model_dump_json()
    # And the same when the phone refuses: a refusal that echoed the code would
    # put it in the transcript.
    bridge.handlers["agent.pair"] = lambda p: _err(-32002, f"code {CODE} is wrong")
    refused = agent_ops.agent_pair(cfg, code=CODE)
    assert CODE not in refused.model_dump_json()


def test_the_pairing_expiry_is_the_codes_not_the_pairings(env) -> None:
    cfg, _bridge, _recorder = env
    result = agent_ops.agent_pair(cfg, code=CODE)
    assert result.code_expires_utc == "2026-09-08T12:00:00Z"
    stored = json.loads(agent_ops.state_path(cfg).read_text(encoding="utf-8"))
    assert stored["code_expires_utc"] == "2026-09-08T12:00:00Z"
    assert "expires_utc" not in stored


def test_the_state_directory_is_not_world_readable(env) -> None:
    cfg, _bridge, _recorder = env
    agent_ops.agent_pair(cfg, code=CODE)
    mode = stat.S_IMODE(agent_ops.state_path(cfg).parent.stat().st_mode)
    assert mode & 0o077 == 0, oct(mode)


def test_a_code_that_is_not_six_digits_never_reaches_the_phone(env) -> None:
    cfg, bridge, recorder = env
    result = agent_ops.agent_pair(cfg, code="12345")
    assert "six digits" in result.refused_reason
    assert bridge.seen == []
    assert recorder.argvs == []


def test_every_tool_result_is_free_of_the_secret(env, monkeypatch) -> None:
    """Not only the value: the word itself must not appear in any model."""
    cfg, bridge, _recorder = env
    bridge.handlers.update(
        {
            "functions.list": lambda p: {"result": {"source": "searchAppFunctions", "count": 0, "functions": []}},
            "app.list": lambda p: {"result": {"apps": [], "count": 0}},
            "ui.tree": lambda p: {"result": {"tree_id": "t", "window": {}, "nodes": [], "node_count": 0}},
            "ui.screenshot": lambda p: {"result": {"width": 1, "height": 1, "png_base64": TINY_PNG, "bytes": 68}},
            "app.launch": lambda p: {"result": {"ok": True, "component": "com.x/.Y"}},
            "ui.key": lambda p: {"result": {"ok": True}},
            "ui.swipe": lambda p: {"result": {"ok": True}},
            "ui.long_press": lambda p: {"result": {"ok": True}},
            "agent.stop": lambda p: {"result": {"ok": True}},
            "log.clear": lambda p: {"result": {"cleared": 3}},
        }
    )
    pair(cfg)
    results = [
        agent_ops.agent_status(cfg),
        agent_ops.agent_pair(cfg, code=CODE),
        agent_ops.agent_functions(cfg),
        agent_ops.agent_execute(cfg, "com.android.settings", "getBatteryDeviceState"),
        agent_ops.agent_ui_tree(cfg),
        agent_ops.agent_screenshot(cfg),
        agent_ops.agent_tap(cfg, x=1, y=1, dry_run=False, confirm=True),
        agent_ops.agent_long_press(cfg, x=1, y=1, dry_run=False, confirm=True),
        agent_ops.agent_swipe(cfg, 1, 2, 3, 4, dry_run=False, confirm=True),
        agent_ops.agent_type(cfg, text="abc", dry_run=False, confirm=True),
        agent_ops.agent_key(cfg, "home", dry_run=False, confirm=True),
        agent_ops.agent_launch(cfg, package="com.x", dry_run=False, confirm=True),
        agent_ops.agent_apps(cfg),
        agent_ops.agent_log(cfg),
        agent_ops.agent_log(cfg, clear=True, confirm=True),
        agent_ops.agent_stop(cfg, dry_run=False, confirm=True),
    ]
    for result in results:
        dumped = result.model_dump_json()
        assert SECRET not in dumped, type(result).__name__
        assert "token" not in dumped.lower(), type(result).__name__


def test_the_secret_is_scrubbed_out_of_anything_echoed(env) -> None:
    cfg, _bridge, _recorder = env
    scrubbed = agent_ops._scrub(
        {"token": SECRET, "nested": {"Token": SECRET}, "note": f"token={SECRET}"}
    )
    assert SECRET not in json.dumps(scrubbed)


# -- the confirm floor --------------------------------------------------


CONFIRM_TOOLS = {
    "device_agent_execute": (
        lambda cfg, **kw: agent_ops.agent_execute(cfg, "com.android.settings", "setDeviceStateItem", **kw),
        "functions.execute",
    ),
    "device_agent_tap": (lambda cfg, **kw: agent_ops.agent_tap(cfg, x=10, y=20, **kw), "ui.tap"),
    "device_agent_long_press": (
        lambda cfg, **kw: agent_ops.agent_long_press(cfg, x=10, y=20, **kw), "ui.long_press",
    ),
    "device_agent_swipe": (lambda cfg, **kw: agent_ops.agent_swipe(cfg, 1, 2, 3, 4, **kw), "ui.swipe"),
    "device_agent_type": (lambda cfg, **kw: agent_ops.agent_type(cfg, text="hello", **kw), "ui.type"),
    "device_agent_key": (lambda cfg, **kw: agent_ops.agent_key(cfg, "home", **kw), "ui.key"),
    "device_agent_launch": (
        lambda cfg, **kw: agent_ops.agent_launch(cfg, package="com.android.settings", **kw), "app.launch",
    ),
    "device_agent_stop": (lambda cfg, **kw: agent_ops.agent_stop(cfg, **kw), "agent.stop"),
}


@pytest.mark.parametrize("name", sorted(CONFIRM_TOOLS))
def test_an_action_needs_both_fields(env, name: str) -> None:
    cfg, bridge, recorder = env
    pair(cfg)
    call, method = CONFIRM_TOOLS[name]

    default = call(cfg)
    assert "dry_run" in default.refused_reason
    unconfirmed = call(cfg, dry_run=False, confirm=False)
    assert "confirm=true" in unconfirmed.refused_reason
    # Neither reached the phone, and neither ran adb.
    assert bridge.seen == []
    assert recorder.argvs == []

    for refused in (default, unconfirmed):
        request = json.loads(refused.request_preview)
        assert request["method"] == method
        assert request["jsonrpc"] == "2.0"
        assert request["params"]["confirm"] is True


def test_the_confirm_list_in_the_config_matches_the_tools() -> None:
    """bestrom://config claims these refuse without confirm. They do."""
    for name in CONFIRM_TOOLS:
        assert name in CONFIRM_REQUIRED_TOOLS
    assert "device_agent_log" in CONFIRM_REQUIRED_TOOLS


def test_clearing_the_on_device_log_needs_confirm(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    result = agent_ops.agent_log(cfg, clear=True)
    assert "confirm=true" in result.refused_reason
    assert json.loads(result.request_preview)["method"] == "log.clear"
    assert bridge.seen == []


def test_a_confirmed_action_sends_confirm_to_the_phone_as_well(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    result = agent_ops.agent_tap(cfg, x=10, y=20, dry_run=False, confirm=True)
    assert result.ok is True
    sent = [r for r in bridge.seen if r["method"] == "ui.tap"][0]
    assert sent["params"] == {"x": 10, "y": 20, "confirm": True}


def test_a_tap_reports_how_it_landed(env) -> None:
    """method is what was called; via is how the phone carried it out."""
    cfg, bridge, _recorder = env
    pair(cfg)
    node = agent_ops.agent_tap(cfg, x=1, y=2, dry_run=False, confirm=True)
    assert node.method == "ui.tap"
    assert node.via == "node"
    bridge.handlers["ui.tap"] = lambda p: {"result": {"ok": True, "method": "gesture"}}
    gesture = agent_ops.agent_tap(cfg, x=1, y=2, dry_run=False, confirm=True)
    assert gesture.method == "ui.tap"
    # "It said ok and nothing happened" is nearly always this.
    assert gesture.via == "gesture"
    bridge.handlers["ui.long_press"] = lambda p: {"result": {"ok": True, "method": "gesture"}}
    held = agent_ops.agent_long_press(cfg, x=1, y=2, dry_run=False, confirm=True)
    assert held.via == "gesture"


def test_the_log_can_be_narrowed_to_one_window(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    agent_ops.agent_log(cfg, limit=5)
    agent_ops.agent_log(cfg, limit=5, since_utc="2026-09-08T12:00:00Z")
    sent = [r["params"] for r in bridge.seen if r["method"] == "log.list"]
    assert sent[0] == {"limit": 5}
    assert sent[1] == {"limit": 5, "since_utc": "2026-09-08T12:00:00Z"}


def test_type_never_echoes_the_text(env, caplog) -> None:
    cfg, _bridge, _recorder = env
    pair(cfg)
    secret_text = "correct-horse-battery-staple"
    dry = agent_ops.agent_type(cfg, text=secret_text)
    assert secret_text not in dry.model_dump_json()
    assert "28 chars" in dry.request_preview
    sent = agent_ops.agent_type(cfg, text=secret_text, dry_run=False, confirm=True)
    assert sent.chars == len(secret_text)
    assert secret_text not in sent.model_dump_json()
    assert secret_text not in caplog.text


def test_launch_takes_exactly_one_target(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    both = agent_ops.agent_launch(cfg, package="com.x", component="com.x/.Y", dry_run=False, confirm=True)
    assert "exactly one" in both.refused_reason
    neither = agent_ops.agent_launch(cfg, dry_run=False, confirm=True)
    assert "exactly one" in neither.refused_reason
    assert bridge.seen == []


def test_a_tap_is_either_a_node_or_a_point(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    both = agent_ops.agent_tap(cfg, tree_id="t", node_id=3, x=1, y=2, dry_run=False, confirm=True)
    assert "not both" in both.refused_reason
    orphan = agent_ops.agent_tap(cfg, node_id=3, dry_run=False, confirm=True)
    assert "tree_id" in orphan.refused_reason
    assert bridge.seen == []


# -- unpaired -----------------------------------------------------------


def test_an_unpaired_server_refuses_before_it_connects(env) -> None:
    cfg, bridge, recorder = env
    result = agent_ops.agent_tap(cfg, x=1, y=1, dry_run=False, confirm=True)
    assert "device_agent_pair" in result.refused_reason
    assert bridge.seen == []
    assert recorder.argvs == []


def test_a_pairing_the_phone_no_longer_knows_says_so(env) -> None:
    cfg, bridge, _recorder = env
    agent_ops.write_secret(cfg, "Zz" + SECRET[2:])
    bridge.handlers["agent.auth"] = lambda p: _err(-32001, "no session")
    result = agent_ops.agent_log(cfg)
    assert "does not survive a reboot" in result.refused_reason
    status = agent_ops.agent_status(cfg)
    # hello still answers, so the bridge is up even though we are not paired.
    assert status.bridge_up is True
    assert status.paired is False


# -- error mapping ------------------------------------------------------


@pytest.mark.parametrize(
    "code,fragment",
    [
        (-32003, "confirm"),
        (-32004, "Agent mode is off"),
        (-32005, "the phone is locked"),
        (-32006, "touching the screen"),
        (-32007, "rate limited"),
        (-32008, "no node with that id"),
        (-32011, "stale"),
        (-32012, "blocked"),
        (-32013, "minimum interval" if False else "refused the screenshot"),
        (-32014, "timed the call out"),
        (-32015, "not installed"),
    ],
)
def test_a_bridge_error_becomes_a_sentence(env, code: int, fragment: str) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["ui.tap"] = lambda p, code=code: _err(code, "refused")
    result = agent_ops.agent_tap(cfg, x=1, y=1, dry_run=False, confirm=True)
    assert result.ok is False
    assert fragment in result.refused_reason, result.refused_reason
    assert result.error is not None
    assert result.error.code == code
    assert result.error.name == agent_ops.ERROR_NAMES[code]


def test_an_app_function_error_carries_its_own_code_through(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["functions.execute"] = lambda p: _err(
        -32010, "the function failed",
        {"code": 1000, "category": "DENIED", "message": "caller not allowlisted"},
    )
    result = agent_ops.agent_execute(
        cfg, "com.android.settings", "setDeviceStateItem", dry_run=False, confirm=True
    )
    assert result.ok is False
    assert result.error.code == -32010
    assert result.error.data["code"] == 1000
    assert result.error.data["category"] == "DENIED"


def test_a_secure_window_is_not_an_empty_screen(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["ui.tree"] = lambda p: _err(-32012, "secure window")
    tree = agent_ops.agent_ui_tree(cfg)
    assert tree.nodes == []
    assert "blocked" in tree.refused_reason
    assert tree.error.name == "SECURE_WINDOW"


# -- app functions ------------------------------------------------------
#
# The phone flattens a GenericDocument to build this, so a property that is
# repeated comes back as a JSON ARRAY. setDeviceStateItem takes two parameters,
# which means anything that types these fields as an object raises rather than
# returning — and it raises on exactly the functions this phase exists to
# expose. The fake bridge used to answer functions: [], which is why nothing
# caught it.

MULTI_PARAM = {
    "package": "com.android.settings",
    "function_id": "setDeviceStateItem",
    "enabled": True,
    "description": "Set one device state item",
    "schema": {"category": "device_state", "name": "setDeviceStateItem", "version": 2},
    "parameters": [
        {"name": "itemId", "dataType": 5, "isRequired": True},
        {"name": "value", "dataType": 5, "isRequired": True},
    ],
    "response": [{"name": "success", "dataType": 6}],
}

# An older build of the app collapsed a one-element array to the object itself.
# Both shapes have to survive, and both have to come back as a list, so the type
# does not change with the number of parameters.
SINGLE_PARAM = {
    "package": "com.android.settings",
    "function_id": "getBatteryDeviceState",
    "schema": {"category": "device_state", "name": "getBatteryDeviceState", "version": 2},
    "parameters": {"name": "includeHistory", "dataType": 6},
}


def test_a_multi_parameter_function_is_returned_not_raised(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["functions.list"] = lambda p: {
        "result": {
            "source": "searchAppFunctions",
            "count": 2,
            "functions": [MULTI_PARAM, SINGLE_PARAM],
        }
    }
    result = agent_ops.agent_functions(cfg)
    assert result.refused_reason == ""
    assert result.notes == []
    assert [f.function_id for f in result.functions] == [
        "setDeviceStateItem",
        "getBatteryDeviceState",
    ]
    assert len(result.functions[0].parameters) == 2
    assert result.functions[0].parameters[0]["name"] == "itemId"
    assert result.functions[0].response == [{"name": "success", "dataType": 6}]
    assert result.functions[1].parameters == [{"name": "includeHistory", "dataType": 6}]
    assert result.functions[1].response is None


def test_one_unmodellable_function_becomes_a_note(env) -> None:
    """One odd entry costs that entry, not the whole call."""
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["functions.list"] = lambda p: {
        "result": {
            "source": "searchAppFunctions",
            "count": 2,
            "functions": [{"function_id": "brokenOne", "parameters": 7}, MULTI_PARAM],
        }
    }
    result = agent_ops.agent_functions(cfg)
    assert [f.function_id for f in result.functions] == ["setDeviceStateItem"]
    assert len(result.notes) == 1
    assert "brokenOne" in result.notes[0]


def test_the_appsearch_fallback_reason_is_surfaced(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["functions.list"] = lambda p: {
        "result": {
            "source": "appsearch",
            "count": 0,
            "functions": [],
            "fallback_reason": "AppFunctionManager was null",
        }
    }
    result = agent_ops.agent_functions(cfg)
    # Without the reason, "nothing is indexed" and "the manager is broken" are
    # the same answer: source=appsearch, count=0.
    assert result.fallback_reason == "AppFunctionManager was null"
    assert result.count == 0


# -- deadlines ----------------------------------------------------------


def test_the_slow_calls_ask_for_a_longer_deadline(env, monkeypatch) -> None:
    """functions.list can take 30 s on the phone; the default socket wait is 30."""
    cfg, _bridge, _recorder = env
    pair(cfg)
    asked: dict[str, int | None] = {}

    def record(cfg_, method, params=None, *, authenticate=True, timeout_s=None):
        asked[method] = timeout_s
        return agent_ops.Reply(result={"ok": True})

    monkeypatch.setattr(agent_ops, "request", record)
    agent_ops.agent_functions(cfg)
    agent_ops.agent_execute(
        cfg, "com.android.settings", "setDeviceStateItem",
        timeout_s=cfg.agent.max_request_timeout_s, dry_run=False, confirm=True,
    )
    assert asked["functions.list"] > cfg.agent.request_timeout_s
    # The +5 the execute tool adds has to survive the socket clamp, or at the
    # top of the range the host reports a socket timeout instead of the phone's
    # own -32014.
    ceiling = cfg.agent.max_request_timeout_s + 5
    assert asked["functions.execute"] == ceiling
    assert agent_ops.socket_deadline(cfg, ceiling) == ceiling


# -- evidence -----------------------------------------------------------


def test_a_screenshot_is_a_file_not_base64(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["ui.screenshot"] = lambda p: {
        "result": {"width": 1, "height": 1, "png_base64": TINY_PNG, "bytes": 68}
    }
    shot = agent_ops.agent_screenshot(cfg)
    assert shot.refused_reason == ""
    path = Path(shot.path)
    assert path.is_file()
    assert path.parent == cfg.agent.evidence_root
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert TINY_PNG not in shot.model_dump_json()
    # A second capture never overwrites the first.
    again = agent_ops.agent_screenshot(cfg)
    assert again.path != shot.path


def test_a_big_tree_spills_to_disk_with_a_preview(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    nodes = [{"id": i, "cls": "View", "text": f"row {i}"} for i in range(500)]
    bridge.handlers["ui.tree"] = lambda p: {
        "result": {
            "tree_id": "deadbeefdeadbeef",
            "window": {"package": "com.android.settings", "title": "Settings", "bounds": [0, 0, 1220, 2712]},
            "nodes": nodes,
            "node_count": len(nodes),
            "truncated": False,
        }
    }
    tree = agent_ops.agent_ui_tree(cfg)
    assert tree.node_count == 500
    assert tree.file
    assert len(tree.nodes) == cfg.agent.inline_node_limit
    assert tree.truncated is True
    written = json.loads(Path(tree.file).read_text(encoding="utf-8"))
    assert len(written["nodes"]) == 500


def test_out_dir_cannot_escape_the_evidence_root(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["ui.screenshot"] = lambda p: {
        "result": {"width": 1, "height": 1, "png_base64": TINY_PNG}
    }
    refused = agent_ops.agent_screenshot(cfg, out_dir=str(cfg.tree.root / "vendor"))
    assert "must live under" in refused.refused_reason
    assert refused.path == ""
    outside = agent_ops.agent_screenshot(cfg, out_dir="/etc")
    assert "outside the allowlist" in outside.refused_reason


def test_out_dir_is_confined_to_the_agents_own_root(env, tmp_path) -> None:
    """Not merely to evidence_dir, which is the whole crash-sweep directory."""
    cfg, _bridge, _recorder = env
    # The allowlist is the real tree in this fixture, so widen it to tmp_path:
    # what is under test is the second, narrower check.
    cfg = replace(cfg, safety=replace(cfg.safety, allowlist_roots=(tmp_path,)))
    inside = agent_ops.evidence_root(cfg, str(cfg.agent.evidence_root / "t12"))
    assert inside == cfg.agent.evidence_root / "t12"
    with pytest.raises(ValueError, match="must live under"):
        agent_ops.evidence_root(cfg, str(cfg.agent.evidence_dir))
    with pytest.raises(ValueError, match=str(cfg.agent.evidence_root)):
        agent_ops.evidence_root(cfg, str(cfg.agent.evidence_dir / "sweep-2026"))


# -- the closed method set ----------------------------------------------


def test_a_desynced_reply_is_reported_not_returned(env) -> None:
    """An answer carrying another call's id is a broken stream, not a result."""
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["log.list"] = lambda p: {"id": 99, "result": {"entries": [], "total": 7}}
    result = agent_ops.agent_log(cfg)
    assert "out of step" in result.refused_reason
    assert result.total == 0


def test_an_error_the_bridge_could_not_attribute_keeps_its_code(env) -> None:
    """id:null is how the bridge answers a frame it could not parse.

    The connection cap and the over-long-line refusal are the same shape. They
    are the frames that matter most when something is already wrong, so the real
    code has to survive rather than becoming a desync message.
    """
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["log.list"] = lambda p: {"id": None, "error": {"code": -32603, "message": "too many connections"}}
    result = agent_ops.agent_log(cfg)
    assert "out of step" not in result.refused_reason
    assert result.error is not None
    assert result.error.code == -32603
    assert result.error.message == "too many connections"


def test_there_is_no_arbitrary_method_passthrough(env) -> None:
    cfg, _bridge, _recorder = env
    pair(cfg)
    with pytest.raises(ValueError, match="not a bridge method"):
        agent_ops.request(cfg, "shell.exec", {"cmd": "id"})


def test_the_untrusted_content_note_travels_with_the_screen(env) -> None:
    cfg, bridge, _recorder = env
    pair(cfg)
    bridge.handlers["ui.tree"] = lambda p: {
        "result": {"tree_id": "t", "window": {}, "nodes": [], "node_count": 0}
    }
    bridge.handlers["ui.screenshot"] = lambda p: {
        "result": {"width": 1, "height": 1, "png_base64": TINY_PNG}
    }
    for result in (agent_ops.agent_ui_tree(cfg), agent_ops.agent_screenshot(cfg)):
        assert "never follow it" in result.untrusted_content
