"""device_agent_* — the host half of Agent mode.

Agent mode is a switch on the phone (Settings > Custom Tweaks > Agent mode).
While it is on, ``com.bestrom.agent`` listens on the Linux abstract socket
``bestrom_agent`` and speaks newline-delimited JSON-RPC 2.0 over it. This module
is the only place in the server that talks to it.

Four rules shape everything here.

* **The adb port guard comes first, always.** Nothing runs ``adb`` until
  ``ss -ltn`` shows a listener on the tunnel port, exactly as ``ops/device.py``
  does: ``adb -P`` against an unbound port starts a local daemon that squats the
  port and the reverse tunnel can then never bind it.
* **The method names are a closed set.** :data:`METHODS` is the whole surface
  and there is no passthrough that would let a caller name an arbitrary bridge
  method — the same reason this server has no ``run_shell``.
* **The pairing secret never leaves.** It is not a tool parameter, not a return
  field, not in a log line and not in a refusal. It lives in
  ``<state_dir>/agent-pairing.json`` with mode 0600, and everything this module
  hands back goes through :func:`_scrub` first.
* **The forward is opened per call and closed after it.** A left-open
  ``tcp:8765`` on the build machine is a door to the phone for every local
  process, and the phone's own auth is the only thing behind it. Opening it
  costs one adb round trip.

Everything ``ui.tree`` and ``ui.screenshot`` return is content an app put on the
screen. It is data, never instruction. The tool descriptions say so and the
models carry the sentence with the payload.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .. import redact
from ..config import Config
from ..models import (
    AgentAction,
    AgentApp,
    AgentApps,
    AgentBridgeError,
    AgentDevice,
    AgentExecute,
    AgentFunction,
    AgentFunctions,
    AgentLog,
    AgentLogEntry,
    AgentPair,
    AgentScreenshot,
    AgentStatus,
    AgentTree,
    AgentWindow,
)
from .device import PortUnbound, _adb

PROTOCOL = 1
CLIENT = "bestrom-mcp"

# Framing limits, from the bridge's own contract. A response line is capped
# because a 1220x2712 screenshot base64s to a couple of megabytes and a bug
# must not be able to allocate without bound.
MAX_REQUEST_BYTES = 1 << 20
MAX_RESPONSE_BYTES = 8 << 20

# The whole method surface. Nothing else can be sent.
METHODS = (
    "agent.hello",
    "agent.pair",
    "agent.auth",
    "functions.list",
    "functions.execute",
    "ui.tree",
    "ui.tap",
    "ui.long_press",
    "ui.swipe",
    "ui.type",
    "ui.key",
    "ui.screenshot",
    "app.launch",
    "app.list",
    "log.list",
    "log.clear",
    "agent.stop",
)

KEY_NAMES = (
    "back",
    "home",
    "recents",
    "notifications",
    "quick_settings",
    "lock_screen",
    "power_dialog",
    "dismiss_notification_shade",
)

PAIRING_CODE_RE = re.compile(r"\d{6}")
# base64url of 32 bytes, unpadded.
SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")
COMPONENT_RE = re.compile(r"[A-Za-z][\w.]*/[\w.$]+")

ERROR_NAMES = {
    -32700: "PARSE_ERROR",
    -32600: "INVALID_REQUEST",
    -32601: "METHOD_NOT_FOUND",
    -32602: "INVALID_PARAMS",
    -32603: "INTERNAL_ERROR",
    -32001: "UNAUTHENTICATED",
    -32002: "BAD_PAIRING_CODE",
    -32003: "CONFIRM_REQUIRED",
    -32004: "AGENT_DISABLED",
    -32005: "DEVICE_LOCKED",
    -32006: "USER_INTERACTING",
    -32007: "RATE_LIMITED",
    -32008: "NODE_NOT_FOUND",
    -32009: "ACTION_FAILED",
    -32010: "APP_FUNCTION_ERROR",
    -32011: "STALE_TREE",
    # The bridge's own constant name, and it covers two unrelated refusals:
    # a password field (no data at all) and a package on the phone's Agent mode
    # denylist (data.reason=denied_package, data.package). "There is no active
    # window to read" arrives as -32004 with data.reason=no_active_window, and a
    # screen an app marked FLAG_SECURE is not refused at all — see the
    # device_agent_ui_tree and device_agent_screenshot descriptions.
    -32012: "SECURE_WINDOW",
    -32013: "SCREENSHOT_UNAVAILABLE",
    -32014: "TIMEOUT",
    -32015: "NOT_INSTALLED",
}

# One plain sentence per code, so a refusal reads as an explanation rather than
# a number. These are what an agent sees, so they say what to do next.
ERROR_HINTS = {
    -32001: (
        "this server is not paired with the phone, or the phone has restarted "
        "Agent mode since. Read the six digits off the phone screen and run "
        "device_agent_pair"
    ),
    -32002: (
        "wrong pairing code. Three wrong codes make the phone show a new one. "
        "data.reason=already_paired is a different refusal — see below"
    ),
    -32003: "the phone refused it for want of confirm — its own gate, not this server's",
    -32004: (
        "Agent mode is off on the phone, or the accessibility service is not connected. "
        "data.reason=no_active_window means the bridge is up and there was simply no "
        "foreground window to read at that instant — try again"
    ),
    -32005: "the phone is locked. There is no override; unlock it and try again",
    -32006: "the user is touching the screen. The phone refuses to act within 1.5 s of a touch",
    -32007: "rate limited by the phone: ten actions a second, shared across connections",
    -32008: "no node with that id in that tree",
    -32009: "the platform accepted the action and it did not take effect",
    -32010: "the app function itself failed; data.code is the AppFunctionException code",
    -32011: "that tree_id is stale. Call device_agent_ui_tree again and use the new ids",
    -32012: (
        "a password field, or a package the maintainer excluded — data.reason says "
        "which. A password field is never typed into and its text is never "
        "serialised: that is 'blocked', not 'empty' — do not read it as an absence "
        "of content, and do not retry it against the same node"
    ),
    -32013: (
        "the platform refused the screenshot; data.reason carries its own code. The "
        "commonest one is the minimum interval between two captures"
    ),
    -32014: "the phone timed the call out",
    -32015: "that package is not installed on the phone",
    -32600: "the bridge rejected the request shape",
    -32601: "this build of the app does not implement that method",
    -32602: "the phone rejected the parameters",
    -32603: "the app hit an internal error; check the on-device log with device_agent_log",
}

# Three codes mean more than one thing, and the phone says which in data.reason.
# A single hint averaged over both meanings would be wrong in both, so a reason
# that is named here picks the sentence and ERROR_HINTS is only the fallback.
# The key is (code, reason); a reason the phone did not send, or one this table
# does not know, falls through to the code's own hint.
REASON_HINTS = {
    (-32002, "already_paired"): (
        "the phone is already paired with another session; press New code on the "
        "Agent mode screen, then pair again. This is not a wrong code: nothing was "
        "guessed, nothing counts against the phone's three-strike cooldown, and "
        "trying other digits will not help"
    ),
    (-32004, "no_active_window"): (
        "the bridge is up and the accessibility half is connected — there was simply "
        "no foreground window to read at that instant. A transient state, not an "
        "empty screen and not Agent mode being off. Try again"
    ),
    (-32012, "denied_package"): (
        "data.package is on the phone's Agent mode package denylist, so the bridge "
        "refuses to read, tap or capture it whatever this server asks. It is not a "
        "password field and there is nothing to retry. The denylist is edited on the "
        "phone, on the Agent mode screen"
    ),
}

NOT_PAIRED = (
    "this server holds no pairing for the phone. Turn Agent mode on in "
    "Settings > Custom Tweaks > Agent mode and run device_agent_pair with the "
    "six digits it shows."
)


# -- error and reply shapes ---------------------------------------------


@dataclass(frozen=True)
class BridgeError:
    code: int
    message: str = ""
    data: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return ERROR_NAMES.get(self.code, "")

    @property
    def reason(self) -> str:
        """``data.reason`` when it is a string, else "".

        ui.screenshot puts the platform's integer error code in the same field,
        so the type is checked rather than assumed.
        """
        value = self.data.get("reason")
        return value if isinstance(value, str) else ""

    @property
    def hint(self) -> str:
        return REASON_HINTS.get((self.code, self.reason)) or ERROR_HINTS.get(self.code, "")

    def model(self) -> AgentBridgeError:
        return AgentBridgeError(
            code=self.code,
            name=self.name,
            message=redact.scrub(str(self.message))[:400],
            hint=self.hint,
            data=_scrub(self.data),
        )

    def as_reason(self) -> str:
        parts = [p for p in (self.name, self.hint) if p]
        text = ": ".join(parts) if parts else f"bridge error {self.code}"
        return f"{text} ({self.code})"


@dataclass(frozen=True)
class Reply:
    """One bridge round trip, already scrubbed."""

    result: dict = field(default_factory=dict)
    error: BridgeError | None = None
    refused_reason: str = ""
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return not self.refused_reason and self.error is None

    def problem(self) -> str:
        """The single line a tool puts in refused_reason, or ""."""
        if self.refused_reason:
            return self.refused_reason
        if self.error is not None:
            return self.error.as_reason()
        return ""

    def error_model(self) -> AgentBridgeError | None:
        return self.error.model() if self.error is not None else None


# -- scrubbing ----------------------------------------------------------


def _scrub(value):
    """Mask the pairing secret in anything that leaves this module.

    ``redact.scrub`` alone would catch it — ``redact.py`` grew a pattern for the
    43-character base64url shape — but the wire key is known here, so the value
    is replaced outright rather than pattern-matched.
    """
    if isinstance(value, dict):
        return {
            key: (redact.MASK if str(key).lower() == "token" else _scrub(val))
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return redact.scrub(value)
    return value


# -- the pairing state file ---------------------------------------------


def state_path(cfg: Config) -> Path:
    return cfg.state_dir / cfg.agent.state_file


def read_secret(cfg: Config) -> str:
    """The stored pairing secret, or "" — never returned to a caller."""
    try:
        data = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = str(data.get("token") or "")
    return value if SECRET_RE.fullmatch(value) else ""


def write_secret(cfg: Config, value: str, code_expires_utc: str = "") -> bool:
    """Store the pairing secret with mode 0600. Returns whether it was written.

    ``os.open`` only applies the mode when it creates the file, so an existing
    one is chmod'ed as well: a file left behind at 0644 by an older run would
    otherwise stay world-readable. The directory is created 0700 for the same
    reason — a 0600 file under a 0755 directory still advertises its name.

    ``code_expires_utc`` is when the six digits stop being accepted, not when
    this pairing does. The pairing lasts as long as the bridge does.
    """
    if not SECRET_RE.fullmatch(value or ""):
        return False
    path = state_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(
            {
                "token": value,
                "serial": cfg.device.serial,
                "paired_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "code_expires_utc": code_expires_utc,
            },
            indent=2,
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        os.chmod(path, 0o600)
    except OSError:
        return False
    return True


# -- the adb forward ----------------------------------------------------


def _forward_args(cfg: Config) -> list[str]:
    return [
        "-s",
        cfg.device.serial,
        "forward",
        f"tcp:{cfg.agent.port}",
        f"localabstract:{cfg.agent.socket}",
    ]


def forward_spec(cfg: Config) -> str:
    return " ".join(["adb", "-P", str(cfg.device.adb_port), *_forward_args(cfg)])


def unforward_spec(cfg: Config) -> str:
    return f"adb -P {cfg.device.adb_port} forward --remove tcp:{cfg.agent.port}"


def open_forward(cfg: Config) -> str:
    """Set the forward up. Returns "" or the reason it could not be set up."""
    try:
        result = _adb(cfg, _forward_args(cfg), timeout=20)
    except PortUnbound as exc:
        return str(exc)
    if not result.ok:
        return (
            f"adb forward failed (rc={result.rc}): {result.err.strip()[:200] or result.out.strip()[:200]}. "
            f"Undo by hand with: {unforward_spec(cfg)}"
        )
    return ""


def close_forward(cfg: Config) -> None:
    """Best effort. A forward left open is a door to the phone, not a leak of state."""
    try:
        _adb(cfg, ["-s", cfg.device.serial, "forward", "--remove", f"tcp:{cfg.agent.port}"], timeout=20)
    except (PortUnbound, OSError):
        return


# -- framing ------------------------------------------------------------


def _encode(payload: dict) -> bytes:
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(line) + 1 > MAX_REQUEST_BYTES:
        raise ValueError(
            f"the request is {len(line)} bytes; the bridge caps a request line at "
            f"{MAX_REQUEST_BYTES}"
        )
    return line + b"\n"


def _read_line(sock: socket.socket) -> bytes:
    """One 0x0A-terminated line, reassembled across recv boundaries.

    Bytes are accumulated and decoded only once the terminator is in hand, so a
    chunk that ends in the middle of a UTF-8 sequence is harmless. JSON escapes
    every newline inside a string, so splitting on 0x0A is safe.
    """
    buffer = bytearray()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("the bridge closed the connection before answering")
        buffer += chunk
        index = buffer.find(b"\n")
        if index >= 0:
            return bytes(buffer[:index])
        if len(buffer) > MAX_RESPONSE_BYTES:
            raise ConnectionError(
                f"the bridge sent more than {MAX_RESPONSE_BYTES} bytes without a newline"
            )


def _exchange(sock: socket.socket, request_id: int, method: str, params: dict) -> Reply:
    sock.sendall(_encode({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}))
    raw = _read_line(sock)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Reply(refused_reason=f"the bridge answered with something that is not JSON: {exc}")
    if not isinstance(payload, dict):
        return Reply(refused_reason="the bridge answered with a JSON value that is not an object")
    answered_id = payload.get("id")
    error = payload.get("error")
    if answered_id != request_id and not (answered_id is None and isinstance(error, dict)):
        # One request in flight per connection, so this cannot happen unless the
        # stream has desynced. Saying so beats reporting another call's answer.
        return Reply(
            refused_reason=(
                f"the bridge answered id {answered_id!r} to request {request_id}; "
                "the connection is out of step"
            )
        )
    if isinstance(error, dict) or "error" in payload:
        # id:null is the bridge's shape for a failure it could not attribute to a
        # request: a parse error, a bad request shape, or the refusal of a fifth
        # connection. Those are the frames that matter most when something is
        # already wrong, so the real code and message go through rather than a
        # desync message that names none of it.
        err = error if isinstance(error, dict) else {}
        data = err.get("data")
        return Reply(
            error=BridgeError(
                code=int(err.get("code", -32603)),
                message=str(err.get("message", "")),
                data=data if isinstance(data, dict) else {},
            )
        )
    result = payload.get("result")
    # Not scrubbed here: agent.pair's result IS the secret, and this is the
    # function that has to hand it to write_secret. Scrubbing happens where a
    # raw sub-object is put into a model, which is the only way anything from
    # the bridge reaches a caller.
    return Reply(result=result if isinstance(result, dict) else {})


# -- one session --------------------------------------------------------


STALE_PAIRING = (
    "the phone did not recognise this server's pairing. Agent mode issues a new "
    "one every time it starts and it does not survive a reboot, so re-run "
    "device_agent_pair with the six digits on the phone screen."
)


@dataclass
class Session:
    """The replies of one connection, plus whether the secret was accepted."""

    replies: list[Reply] = field(default_factory=list)
    authenticated: bool = False
    auth_problem: str = ""


# How much longer than the phone's own deadline the socket is allowed to wait.
# A tool that asks the phone for 120 s asks this socket for 125, so the phone's
# -32014 wins the race and the maintainer is told the call timed out rather than
# the socket did. Clamping at max_request_timeout_s threw that headroom away at
# the top of the range, which is where it is needed most.
DEADLINE_HEADROOM_S = 10


def socket_deadline(cfg: Config, timeout_s: int | None = None) -> int:
    """The socket timeout for a call that asked for *timeout_s* seconds."""
    asked = int(timeout_s or cfg.agent.request_timeout_s)
    return max(5, min(asked, cfg.agent.max_request_timeout_s + DEADLINE_HEADROOM_S))


def _session(
    cfg: Config,
    calls: list[tuple[str, dict]],
    *,
    auth: str = "required",
    timeout_s: int | None = None,
) -> Session:
    """Forward, connect, authenticate, run *calls* in order, close.

    ``auth`` is "required" (refuse when unpaired), "optional" (authenticate when
    a pairing is stored, carry on either way — what device_agent_status wants)
    or "none". A fresh connection per tool call keeps this server stateless: a
    hung call cannot wedge the next one, and the cost is one ``agent.auth``.
    """
    for method, _params in calls:
        if method not in METHODS:
            raise ValueError(f"{method} is not a bridge method")

    def failed(reason: str) -> Session:
        return Session(replies=[Reply(refused_reason=reason) for _ in calls], auth_problem=reason)

    secret = read_secret(cfg) if auth in ("required", "optional") else ""
    if auth == "required" and not secret:
        return failed(NOT_PAIRED)

    problem = open_forward(cfg)
    if problem:
        return failed(problem)

    timeout = socket_deadline(cfg, timeout_s)
    try:
        sock = socket.create_connection(
            (cfg.device.adb_host, cfg.agent.port), timeout=cfg.agent.connect_timeout_s
        )
    except OSError as exc:
        close_forward(cfg)
        return failed(
            f"nothing accepted a connection on {cfg.device.adb_host}:{cfg.agent.port} ({exc}). "
            "The forward is in place, so Agent mode is most likely off on the phone: "
            "Settings > Custom Tweaks > Agent mode."
        )

    session = Session()
    request_id = 0
    try:
        sock.settimeout(timeout)
        if secret:
            request_id += 1
            handshake = _exchange(sock, request_id, "agent.auth", {"token": secret})
            if handshake.ok:
                session.authenticated = True
            else:
                stale = handshake.error is not None and handshake.error.code == -32001
                session.auth_problem = STALE_PAIRING if stale else handshake.problem()
                if auth == "required":
                    return failed(session.auth_problem)
        for method, params in calls:
            request_id += 1
            started = time.monotonic()
            reply = _exchange(sock, request_id, method, params)
            session.replies.append(
                Reply(
                    result=reply.result,
                    error=reply.error,
                    refused_reason=reply.refused_reason,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            )
    except (TimeoutError, socket.timeout):
        pending = calls[len(session.replies)][0] if len(session.replies) < len(calls) else "the call"
        reason = (
            f"the bridge did not answer {pending} within {timeout} s. Nothing says whether it "
            "acted; check device_agent_log before retrying an action."
        )
        while len(session.replies) < len(calls):
            session.replies.append(Reply(refused_reason=reason))
    except (ConnectionError, OSError, ValueError) as exc:
        reason = f"the bridge socket failed: {exc}"
        while len(session.replies) < len(calls):
            session.replies.append(Reply(refused_reason=reason))
    finally:
        try:
            sock.close()
        finally:
            close_forward(cfg)
    return session


def request(
    cfg: Config,
    method: str,
    params: dict | None = None,
    *,
    authenticate: bool = True,
    timeout_s: int | None = None,
) -> Reply:
    """One authenticated round trip to the bridge."""
    session = _session(
        cfg,
        [(method, dict(params or {}))],
        auth="required" if authenticate else "none",
        timeout_s=timeout_s,
    )
    return session.replies[0]


# -- the confirm floor --------------------------------------------------


def confirm_gate(dry_run: bool, confirm: bool, what: str) -> str:
    """The refusal, or "" when the call may proceed.

    Same two fields as ``device_sideload`` and ``repo_sync``: ``dry_run=false``
    AND ``confirm=true``, so no single flipped field reaches the action. The
    phone applies the same floor again on its side.
    """
    if dry_run:
        return f"dry_run is true, so nothing was sent. Pass dry_run=false and confirm=true to {what}."
    if not confirm:
        return f"dry_run=false and confirm=true are both required to {what}"
    return ""


def preview(method: str, params: dict) -> str:
    """The exact JSON-RPC line that would go down the socket."""
    return json.dumps(
        {"jsonrpc": "2.0", "id": 2, "method": method, "params": _scrub(params)},
        ensure_ascii=False,
        sort_keys=True,
    )


# -- evidence -----------------------------------------------------------


def evidence_root(cfg: Config, out_dir: str = "") -> Path:
    """Where a screenshot or a spilled tree goes.

    ``out_dir`` is resolved against the path allowlist and then confined to the
    evidence root, the same narrowing ``device_capture`` applies. The confinement
    is against the agent's own root — ``<evidence_dir>/agent`` — and not against
    ``evidence_dir``, which would let a screenshot land anywhere in the whole
    crash-sweep directory.
    """
    root = cfg.agent.evidence_root
    if out_dir:
        target = cfg.resolve_allowed(out_dir)
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"out_dir must live under {root}") from exc
    else:
        target = root
    target.mkdir(parents=True, exist_ok=True)
    return target


def _stamped(target: Path, prefix: str, suffix: str) -> Path:
    """A timestamped name that never overwrites an earlier capture."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = target / f"{prefix}-{stamp}{suffix}"
    counter = 1
    while path.exists():
        path = target / f"{prefix}-{stamp}-{counter}{suffix}"
        counter += 1
    return path


# -- status and pairing -------------------------------------------------


def agent_status(cfg: Config) -> AgentStatus:
    spec = forward_spec(cfg)
    session = _session(
        cfg, [("agent.hello", {"client": CLIENT, "protocol": PROTOCOL})], auth="optional"
    )
    reply = session.replies[0]
    if not reply.ok:
        return AgentStatus(
            forward_spec=spec,
            refused_reason=(
                reply.problem() + f" Undo the forward by hand with: {unforward_spec(cfg)}"
            ),
            error=reply.error_model(),
        )
    result = reply.result
    state = result.get("state") or {}
    device = result.get("device") or {}
    return AgentStatus(
        bridge_up=True,
        # Paired means the phone accepted this server's pairing on this very
        # connection, not that a file exists on disk.
        paired=session.authenticated,
        forward_spec=spec,
        protocol=int(result.get("protocol") or 0),
        app_version=str(result.get("app_version") or ""),
        capabilities=[str(c) for c in (result.get("capabilities") or [])],
        a11y_connected=bool(state.get("a11y_connected")),
        keyguard_locked=bool(state.get("keyguard_locked")),
        idle_timeout_s=int(state.get("idle_timeout_s") or 0),
        rate_limit_per_s=int(state.get("rate_limit_per_s") or 0),
        device=AgentDevice(
            model=str(device.get("model") or ""),
            device=str(device.get("device") or ""),
            sdk=int(device.get("sdk") or 0),
            fingerprint=str(device.get("fingerprint") or ""),
            bestrom_version=str(device.get("bestrom_version") or ""),
        ),
        refused_reason=("" if session.authenticated else (session.auth_problem or NOT_PAIRED)),
    )


def agent_pair(cfg: Config, code: str) -> AgentPair:
    code = (code or "").strip()
    if not PAIRING_CODE_RE.fullmatch(code):
        return AgentPair(refused_reason="code must be the six digits shown on the phone screen")
    reply = request(cfg, "agent.pair", {"code": code}, authenticate=False)
    if not reply.ok:
        # No strike counter lives here, deliberately. The phone owns the three
        # wrong codes and the cooldown, and -32002 has two meanings: a wrong
        # code, and data.reason=already_paired, which is not a guess at all and
        # which the phone itself does not count. A local tally would turn the
        # second into a lockout this server invented. The stored pairing is left
        # exactly as it was either way — a refused pair is not a reason to throw
        # away a pairing that may still be good.
        return AgentPair(refused_reason=reply.problem(), error=reply.error_model())
    # code_expires_utc is the CODE's expiry. The code is single use: pairing
    # consumes it, and a second client needs the phone's "New code" button. What
    # ends this pairing is the bridge stopping — a reboot, the idle timeout, the
    # switch or agent.stop — not that timestamp passing.
    expires = str(reply.result.get("code_expires_utc") or "")
    stored = write_secret(cfg, str(reply.result.get("token") or ""), expires)
    return AgentPair(
        paired=stored,
        stored=stored,
        capabilities=[str(c) for c in (reply.result.get("capabilities") or [])],
        code_expires_utc=expires,
        refused_reason=(
            ""
            if stored
            else f"the phone paired but {state_path(cfg)} could not be written, so the pairing is lost"
        ),
    )


# -- app functions ------------------------------------------------------


# functions.list is the slowest call on the wire: the phone budgets 15 s for
# searchAppFunctions and another 15 s for getAppFunctionStates, so a cold first
# discovery can take 30 s. The default request timeout is 30 s too, which turns
# a slow answer into a socket timeout at random.
FUNCTIONS_TIMEOUT_S = 45

# The two values the phone puts in fallback_reason, verbatim, each with the one
# line that says what the list in hand is worth. The reason itself is passed
# through untouched — a value this table does not know still reaches the caller,
# it just arrives without a hint.
FALLBACK_HINTS = {
    "app_function_manager_unavailable": (
        "the phone could not get AppFunctionManager at all, so this list is the raw "
        "AppSearch index: enabled is assumed true and device_agent_execute will fail "
        "with a system error until that service is back"
    ),
    "search_app_functions_failed": (
        "searchAppFunctions failed or missed the phone's 10 s budget, so this list is "
        "the raw AppSearch index: it can be stale or short, and enabled is assumed "
        "true. Executing still works — try the list again before believing a gap"
    ),
}


def agent_functions(cfg: Config, package: str = "", include_schema: bool = True) -> AgentFunctions:
    params: dict = {"include_schema": bool(include_schema)}
    if package:
        params["package"] = package
    reply = request(cfg, "functions.list", params, timeout_s=FUNCTIONS_TIMEOUT_S)
    if not reply.ok:
        return AgentFunctions(refused_reason=reply.problem(), error=reply.error_model())
    functions = []
    notes: list[str] = []
    for index, entry in enumerate(reply.result.get("functions") or []):
        if not isinstance(entry, dict):
            notes.append(f"entry {index} is not an object and was dropped")
            continue
        schema = entry.get("schema")
        schema = schema if isinstance(schema, dict) else {}
        # One entry the phone shapes differently must not cost the whole list.
        # The metadata comes out of a GenericDocument flattener, so a property
        # that is repeated on one function and scalar on another is a wire fact,
        # not a bug this server can fix.
        try:
            functions.append(
                AgentFunction(
                    package=str(entry.get("package") or ""),
                    function_id=str(entry.get("function_id") or ""),
                    enabled=bool(entry.get("enabled", True)),
                    description=str(entry.get("description") or ""),
                    schema_category=str(schema.get("category") or ""),
                    schema_name=str(schema.get("name") or ""),
                    schema_version=int(schema.get("version") or 0),
                    parameters=_scrub(entry.get("parameters")),
                    response=_scrub(entry.get("response")),
                )
            )
        except (ValidationError, TypeError, ValueError) as exc:
            name = str(entry.get("function_id") or entry.get("package") or f"entry {index}")
            notes.append(f"{name} came back in a shape this server cannot model: {exc}"[:300])
    # Set when the phone had to fall back to the global AppSearch query. Without
    # it "nothing is indexed" and "AppFunctionManager is broken" are the same
    # answer: source=appsearch, count=0.
    fallback = str(reply.result.get("fallback_reason") or "")
    return AgentFunctions(
        source=str(reply.result.get("source") or ""),
        count=int(reply.result.get("count") or len(functions)),
        functions=functions,
        fallback_reason=fallback,
        fallback_hint=FALLBACK_HINTS.get(fallback, ""),
        notes=notes,
    )


def agent_execute(
    cfg: Config,
    package: str,
    function: str,
    params: dict | None = None,
    timeout_s: int = 30,
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentExecute:
    timeout_s = max(5, min(int(timeout_s), cfg.agent.max_request_timeout_s))
    body = {
        "package": package,
        "function": function,
        "params": dict(params or {}),
        "timeout_ms": timeout_s * 1000,
        "confirm": True,
    }
    line = preview("functions.execute", body)
    if not package or not function:
        return AgentExecute(
            dry_run=dry_run,
            request_preview=line,
            refused_reason="package and function are both required",
        )
    refusal = confirm_gate(dry_run, confirm, f"run {function} on {package}")
    if refusal:
        return AgentExecute(dry_run=dry_run, request_preview=line, refused_reason=refusal)

    reply = request(cfg, "functions.execute", body, timeout_s=timeout_s + 5)
    if not reply.ok:
        return AgentExecute(
            dry_run=False,
            request_preview=line,
            refused_reason=reply.problem(),
            error=reply.error_model(),
        )
    extras = reply.result.get("extras") or {}
    return AgentExecute(
        dry_run=False,
        request_preview=line,
        ok=bool(reply.result.get("ok", True)),
        result=_scrub(reply.result.get("result") or {}),
        extras=_scrub(extras) if isinstance(extras, dict) else {},
        pending_intent=bool(isinstance(extras, dict) and extras.get("pending_intent")),
        duration_ms=int(reply.result.get("duration_ms") or reply.duration_ms),
    )


# -- reading the screen -------------------------------------------------


def agent_ui_tree(
    cfg: Config, max_depth: int = 25, max_nodes: int = 800, out_dir: str = ""
) -> AgentTree:
    params = {
        "max_depth": max(1, min(int(max_depth), 100)),
        "max_nodes": max(1, min(int(max_nodes), 5000)),
    }
    reply = request(cfg, "ui.tree", params)
    if not reply.ok:
        return AgentTree(refused_reason=reply.problem(), error=reply.error_model())
    result = reply.result
    window = result.get("window") or {}
    nodes = _scrub([n for n in (result.get("nodes") or []) if isinstance(n, dict)])
    tree = AgentTree(
        tree_id=str(result.get("tree_id") or ""),
        window=AgentWindow(
            package=str(window.get("package") or ""),
            title=str(window.get("title") or ""),
            bounds=[int(b) for b in (window.get("bounds") or []) if isinstance(b, (int, float))],
        ),
        node_count=int(result.get("node_count") or len(nodes)),
        truncated=bool(result.get("truncated")),
    )
    limit = cfg.agent.inline_node_limit
    if len(nodes) <= limit:
        tree.nodes = nodes
        return tree
    # A big tree is a file plus a preview: returning 800 nodes inline is how a
    # context window is spent on a screen nobody read.
    try:
        target = evidence_root(cfg, out_dir)
        path = _stamped(target, "agent-tree", ".json")
        path.write_text(json.dumps(_scrub(result), indent=2), encoding="utf-8")
        tree.file = str(path)
    except (OSError, ValueError) as exc:
        tree.refused_reason = f"the tree could not be written to disk: {exc}"
    tree.nodes = nodes[:limit]
    tree.truncated = True
    return tree


def agent_screenshot(cfg: Config, out_dir: str = "") -> AgentScreenshot:
    reply = request(cfg, "ui.screenshot", {"encoding": "base64"})
    if not reply.ok:
        return AgentScreenshot(refused_reason=reply.problem(), error=reply.error_model())
    encoded = str(reply.result.get("png_base64") or "")
    if not encoded:
        return AgentScreenshot(refused_reason="the bridge returned no image data")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        return AgentScreenshot(refused_reason=f"the image did not decode: {exc}")
    try:
        target = evidence_root(cfg, out_dir)
        path = _stamped(target, "agent-screen", ".png")
        path.write_bytes(raw)
    except (OSError, ValueError) as exc:
        return AgentScreenshot(refused_reason=f"the image could not be written: {exc}")
    return AgentScreenshot(
        path=str(path),
        width=int(reply.result.get("width") or 0),
        height=int(reply.result.get("height") or 0),
        bytes=len(raw),
    )


# -- acting on the screen -----------------------------------------------


def _action(
    cfg: Config,
    method: str,
    body: dict,
    *,
    dry_run: bool,
    confirm: bool,
    what: str,
    target: str = "",
    preview_body: dict | None = None,
) -> AgentAction:
    line = preview(method, preview_body if preview_body is not None else body)
    refusal = confirm_gate(dry_run, confirm, what)
    if refusal:
        return AgentAction(
            dry_run=dry_run, method=method, request_preview=line, target=target, refused_reason=refusal
        )
    reply = request(cfg, method, body)
    if not reply.ok:
        return AgentAction(
            dry_run=False,
            method=method,
            request_preview=line,
            target=target,
            refused_reason=reply.problem(),
            error=reply.error_model(),
        )
    return AgentAction(
        dry_run=False,
        method=method,
        # The phone calls this field "method" too, but it holds how the action
        # was carried out, not what was called. It is renamed here rather than
        # shadowing the JSON-RPC method name: "the tap succeeded and nothing
        # happened" is almost always via=gesture.
        via=str(reply.result.get("method") or ""),
        request_preview=line,
        ok=bool(reply.result.get("ok", True)),
        target=str(reply.result.get("target") or target),
        component=str(reply.result.get("component") or ""),
        chars=int(reply.result.get("chars") or 0),
    )


def _point_params(
    tree_id: str, node_id: int | None, x: int | None, y: int | None
) -> tuple[dict, str, str]:
    """Either (tree_id, node_id) or (x, y). Never both, never neither."""
    by_node = node_id is not None
    by_point = x is not None and y is not None
    if by_node and by_point:
        return {}, "", "pass either tree_id and node_id, or x and y — not both"
    if by_node:
        if not tree_id:
            return {}, "", "node_id needs the tree_id it came from"
        return {"tree_id": tree_id, "node_id": int(node_id)}, f"{tree_id}#{node_id}", ""
    if by_point:
        return {"x": int(x), "y": int(y)}, f"{x},{y}", ""
    return {}, "", "pass either tree_id and node_id, or x and y"


def agent_tap(
    cfg: Config,
    tree_id: str = "",
    node_id: int | None = None,
    x: int | None = None,
    y: int | None = None,
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentAction:
    body, target, problem = _point_params(tree_id, node_id, x, y)
    if problem:
        return AgentAction(dry_run=dry_run, method="ui.tap", refused_reason=problem)
    body["confirm"] = True
    return _action(cfg, "ui.tap", body, dry_run=dry_run, confirm=confirm, what="tap the phone", target=target)


def agent_long_press(
    cfg: Config,
    tree_id: str = "",
    node_id: int | None = None,
    x: int | None = None,
    y: int | None = None,
    duration_ms: int = 600,
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentAction:
    body, target, problem = _point_params(tree_id, node_id, x, y)
    if problem:
        return AgentAction(dry_run=dry_run, method="ui.long_press", refused_reason=problem)
    body["duration_ms"] = max(1, min(int(duration_ms), 3000))
    body["confirm"] = True
    return _action(
        cfg, "ui.long_press", body, dry_run=dry_run, confirm=confirm,
        what="long press on the phone", target=target,
    )


def agent_swipe(
    cfg: Config,
    from_x: int,
    from_y: int,
    to_x: int,
    to_y: int,
    duration_ms: int = 300,
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentAction:
    body = {
        "from": [int(from_x), int(from_y)],
        "to": [int(to_x), int(to_y)],
        "duration_ms": max(1, min(int(duration_ms), 3000)),
        "confirm": True,
    }
    target = f"{from_x},{from_y} -> {to_x},{to_y}"
    return _action(
        cfg, "ui.swipe", body, dry_run=dry_run, confirm=confirm, what="swipe the phone", target=target
    )


def agent_type(
    cfg: Config,
    text: str,
    tree_id: str = "",
    node_id: int | None = None,
    replace: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentAction:
    if len(text) > 4096:
        return AgentAction(
            dry_run=dry_run, method="ui.type", refused_reason="text is capped at 4096 characters"
        )
    if node_id is not None and not tree_id:
        return AgentAction(
            dry_run=dry_run, method="ui.type", refused_reason="node_id needs the tree_id it came from"
        )
    body: dict = {"text": text, "replace": bool(replace), "confirm": True}
    if node_id is not None:
        body["tree_id"] = tree_id
        body["node_id"] = int(node_id)
    # The preview reports the length. The string itself is never echoed back,
    # never logged and never written to the on-device audit log.
    shown = dict(body)
    shown["text"] = f"<{len(text)} chars, not echoed>"
    target = f"{tree_id}#{node_id}" if node_id is not None else "the focused editable node"
    return _action(
        cfg, "ui.type", body, dry_run=dry_run, confirm=confirm,
        what="type into the phone", target=target, preview_body=shown,
    )


def agent_key(cfg: Config, name: str, dry_run: bool = True, confirm: bool = False) -> AgentAction:
    if name not in KEY_NAMES:
        return AgentAction(
            dry_run=dry_run, method="ui.key", refused_reason=f"name must be one of {list(KEY_NAMES)}"
        )
    return _action(
        cfg, "ui.key", {"name": name, "confirm": True}, dry_run=dry_run, confirm=confirm,
        what=f"press {name} on the phone", target=name,
    )


def agent_launch(
    cfg: Config,
    package: str = "",
    component: str = "",
    intent_uri: str = "",
    dry_run: bool = True,
    confirm: bool = False,
) -> AgentAction:
    given = [v for v in (package, component, intent_uri) if v]
    if len(given) != 1:
        return AgentAction(
            dry_run=dry_run,
            method="app.launch",
            refused_reason="pass exactly one of package, component or intent_uri",
        )
    if component and not COMPONENT_RE.fullmatch(component):
        return AgentAction(
            dry_run=dry_run, method="app.launch", refused_reason="component must be pkg/cls"
        )
    body: dict = {"confirm": True}
    if package:
        body["package"] = package
    elif component:
        body["component"] = component
    else:
        body["intent_uri"] = intent_uri
    return _action(
        cfg, "app.launch", body, dry_run=dry_run, confirm=confirm,
        what=f"open {given[0]} on the phone", target=given[0],
    )


def agent_stop(cfg: Config, dry_run: bool = True, confirm: bool = False) -> AgentAction:
    return _action(
        cfg, "agent.stop", {"confirm": True}, dry_run=dry_run, confirm=confirm,
        what="turn Agent mode off on the phone", target="agent mode",
    )


# -- apps and the on-device audit log -----------------------------------


def agent_apps(cfg: Config, launchable_only: bool = True) -> AgentApps:
    reply = request(cfg, "app.list", {"launchable_only": bool(launchable_only)})
    if not reply.ok:
        return AgentApps(refused_reason=reply.problem(), error=reply.error_model())
    apps = []
    for entry in reply.result.get("apps") or []:
        if not isinstance(entry, dict):
            continue
        apps.append(
            AgentApp(
                package=str(entry.get("package") or ""),
                label=str(entry.get("label") or ""),
                version_name=str(entry.get("version_name") or ""),
                version_code=int(entry.get("version_code") or 0),
                system=bool(entry.get("system")),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return AgentApps(count=int(reply.result.get("count") or len(apps)), apps=apps)


def agent_log(
    cfg: Config,
    limit: int = 100,
    clear: bool = False,
    confirm: bool = False,
    since_utc: str = "",
) -> AgentLog:
    if clear:
        line = preview("log.clear", {"confirm": True})
        if not confirm:
            return AgentLog(
                request_preview=line,
                refused_reason=(
                    "confirm=true is required to clear the phone's audit log. It is the only "
                    "record of what the agent did, and clearing it is itself logged."
                ),
            )
        reply = request(cfg, "log.clear", {"confirm": True})
        if not reply.ok:
            return AgentLog(
                request_preview=line, refused_reason=reply.problem(), error=reply.error_model()
            )
        return AgentLog(request_preview=line, cleared=int(reply.result.get("cleared") or 0))

    list_params: dict = {"limit": max(1, min(int(limit), 500))}
    if since_utc:
        # The phone filters on ts_utc >= since_utc, so "what happened during that
        # one action" is one call instead of reading the ring and diffing it.
        list_params["since_utc"] = since_utc
    reply = request(cfg, "log.list", list_params)
    if not reply.ok:
        return AgentLog(refused_reason=reply.problem(), error=reply.error_model())
    entries = []
    for entry in reply.result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        code = entry.get("error_code")
        # peer_uid and connection_id are newer than the first bridge build, so
        # an entry without them is normal rather than malformed: absent stays
        # None instead of collapsing to 0, which is root.
        uid = entry.get("peer_uid")
        conn = entry.get("connection_id")
        entries.append(
            AgentLogEntry(
                ts_utc=str(entry.get("ts_utc") or ""),
                method=str(entry.get("method") or ""),
                target=str(entry.get("target") or ""),
                result=str(entry.get("result") or ""),
                error_code=int(code) if isinstance(code, (int, float)) else None,
                duration_ms=int(entry.get("duration_ms") or 0),
                peer_uid=int(uid) if isinstance(uid, (int, float)) else None,
                connection_id=int(conn) if isinstance(conn, (int, float)) else None,
            )
        )
    return AgentLog(
        entries=entries,
        total=int(reply.result.get("total") or len(entries)),
        capacity=int(reply.result.get("capacity") or 0),
    )
