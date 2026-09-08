# BestROM MCP server

An MCP server that exposes the BestROM build, verify, device and release
workflow as typed tools, so any MCP client — Claude Code, Cursor, Codex — can
drive the ROM without ad-hoc shell and without losing the gates the chain
scripts carry.

It wraps the automation that already exists (`build-bestrom-run.sh`,
`chain-*-build.sh`, `chain-*-verify.sh`, `chain-*-publish.sh`,
`crash-sweep/capture.sh`) rather than reimplementing it, and adds a typed
argument surface, a dry run on every mutating operation, and one redaction pass
over subprocess output.

## Requirements

* **Python 3.11 or newer** (`pyproject.toml` sets `requires-python`).
* **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`. Nothing else is
  needed to start the server — the shipped client entry uses `uv run`, which
  creates the venv on the first connection.
* **`repo` and `git`** on PATH for the tree tools; **`adb`** for the device
  tools.
* **A systemd user session** for `build_start`, and `loginctl enable-linger`
  if builds must survive logout.
* **`git-filter-repo`** only if the maintainer runs the command
  `strip_ai_trailers` hands back. The tool itself never needs it.
* `aapt2` comes from `prebuilts/sdk/tools/linux/bin/aapt2` in the tree; the
  `aapt2_resource_count` checks skip themselves if it is missing.

## Bootstrap

There is no manual step for a client: the entry below runs
`uv run --directory …`, which syncs and creates `.venv/` (git-ignored) on the
first connection. To do it ahead of time, or to run the tests:

    cd vendor/bestrom/tools/mcp
    uv sync --extra dev

Check the install:

    uv run bestrom-mcp --version
    uv run python -m pytest -q

`smoke/stdio_smoke.py` is the full integration check. It skips the parts that
need a completed build (`build_artifacts`, `release_prepare` against a real
package), so it is also safe to run on a fresh clone:

    uv run python smoke/stdio_smoke.py

## Client configuration

**Claude Code** reads the project-scope `.mcp.json` at the tree root, which is a
`<copyfile>` of `vendor/bestrom/tools/mcp.json`:

```json
{
  "mcpServers": {
    "bestrom": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run", "--directory", "${CLAUDE_PROJECT_DIR:-.}/vendor/bestrom/tools/mcp",
        "bestrom-mcp", "--transport", "stdio"
      ],
      "timeout": 600000
    }
  }
}
```

There is no `BESTROM_TREE` in it on purpose. The server derives the tree root by
walking up from its own file, so the variable can only be got wrong; a client
that passes an unexpanded `${…}` through it now fails at connect time with a
message naming the variable, rather than on the fifth tool call.

The `claude mcp add` equivalent, if you would rather not use the file:

    claude mcp add --scope project bestrom -- \
      uv run --directory vendor/bestrom/tools/mcp bestrom-mcp --transport stdio

**Cursor** — `.cursor/mcp.json` in the tree. Cursor does not expand
`${CLAUDE_PROJECT_DIR}`, so use an absolute path:

```json
{
  "mcpServers": {
    "bestrom": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/bestrom-a17/vendor/bestrom/tools/mcp",
        "bestrom-mcp", "--transport", "stdio"
      ]
    }
  }
}
```

**Codex** — `~/.codex/config.toml`, which is TOML with a different key shape:

```toml
[mcp_servers.bestrom]
command = "uv"
args = [
  "run", "--directory", "/path/to/bestrom-a17/vendor/bestrom/tools/mcp",
  "bestrom-mcp", "--transport", "stdio",
]
startup_timeout_sec = 120
```

## Tools

| Tool | Purpose | Safety |
|---|---|---|
| `env_check` | Cores, memory, disk headroom, `out/` size, ccache, envsetup, lunch target, systemd, in-flight build, adb listener | read-only |
| `repo_status` | Branch vs manifest revision, dirty count, ahead/behind, per project | read-only |
| `manifest_check` | Manifest mirror identical, `<copyfile>` entries present, root copies still match | read-only |
| `repo_sync` | `repo sync` from the BestROM manifest | dry_run, confirm, refuses on dirty |
| `tree_repair` | Recreate the seven `build/make` link results a partial sync loses | dry_run, idempotent |
| `build_start` | Launch the canonical build detached, as a systemd `--user` unit | dry_run, refuses when a build is in flight |
| `build_status` | Unit state, `BUILD EXIT: N`, bounded log tail | read-only |
| `build_errors` | Deduplicated `FAILED:`/`error:` extract | read-only |
| `build_cancel` | Stop the unit by name from the job registry | confirm |
| `build_artifacts` | Package name, size, sha256, build.prop identity, delta vs previous | read-only |
| `verify_image` | The image gate, as a declarative profile | writes only the chain marker, and only after a full clean run |
| `device_list` | Device reachability, build fingerprint, root availability | read-only, port-guarded |
| `device_capture` | Structured crash/logcat/dropbox/avc/screenshot/package evidence | writes only under the evidence root |
| `device_sideload` | Emits the flash plan; refuses to flash over the tunnel | dry_run, confirm, disabled in config |
| `device_agent_status` | Is Agent mode up on the phone, is this server paired | read-only, port-guarded |
| `device_agent_pair` | Exchange the six digits on the phone for a stored pairing | the code on the screen is the gate |
| `device_agent_functions` | The app functions the phone publishes, with schemas | read-only |
| `device_agent_execute` | Call one app function | dry_run, confirm |
| `device_agent_ui_tree` | The accessibility tree of the foreground window | untrusted content; spills to the evidence root |
| `device_agent_tap` | Tap a node or a point | dry_run, confirm |
| `device_agent_long_press` | Long press a node or a point | dry_run, confirm |
| `device_agent_swipe` | Drag between two points | dry_run, confirm |
| `device_agent_type` | Set the text of an editable field | dry_run, confirm; text never echoed |
| `device_agent_key` | One accessibility global action | dry_run, confirm |
| `device_agent_screenshot` | A PNG under the evidence root | untrusted content; never inline |
| `device_agent_launch` | Start an activity | dry_run, confirm |
| `device_agent_apps` | Installed apps with labels and versions | read-only |
| `device_agent_log` | The phone's own audit log, with `peer_uid` and `connection_id` per entry; `clear=true` empties it | confirm to clear |
| `device_agent_stop` | The remote kill switch | dry_run, confirm |
| `release_prepare` | The three release documents as drafts | dry_run; publishes nothing |
| `release_publish` | The publish chain, behind both anti-drift gates | dry_run, confirm, gates re-checked, all-or-nothing |
| `changelog_add` | Append a section to `CHANGELOG.md` under "Unreleased" | dry_run; one file |
| `commit_message_check` | The BestROM commit style as a checkable function | pure |
| `strip_ai_trailers` | Report commits carrying AI attribution | read-only; never rewrites |

### Detail

**`env_check`** → `EnvReport`. No inputs. The one call to make before starting
anything expensive: it catches ENOSPC before a two-hour build hits it, and it
refuses to pretend the tree is buildable when `build/envsetup.sh` is missing.
Wraps `df`, `/proc/meminfo`, `du -sb out` (cached for an hour), `ccache -s`,
`repo --version`, `pgrep -x soong_ui`, `systemctl --user is-system-running`,
`ss -ltn`.

**`repo_status`** → `RepoStatus`. `paths`, `include_dirty_scan`. Flags the
branch-versus-manifest mismatch explicitly, because `vendor/bestrom` is often
checked out on a feature branch while the manifest tracks `voltage-17`, and a
commit on the wrong branch never reaches a build.

**`manifest_check`** → `ManifestCheck`. Enforces the reproducibility rule:
`vendor/bestrom/manifest/bestrom.xml` and `.repo/local_manifests/bestrom.xml`
must be byte-identical, the three `<copyfile>` entries must be there, and each
root copy must still hash-match its source under `tools/`. A root file edited in
place is silently lost on the next sync; this is what notices.

**`repo_sync`** → `SyncResult`. A dry run is local by default — manifest
revisions against current branches, dirty projects, the command preview. Pass
`fetch=true` to add `repo sync --network-only`; that is a real network fetch of
an AOSP tree and can run for a long time, so it is not what the first call does.
A real sync needs `confirm=true`, refuses while any project in the publish set
is dirty unless `force_dirty` is also set, and never passes `--force-sync`.

Each entry of `projects` must be a tree-relative path. Anything starting with
`-` is refused and the validated paths are appended after a literal `--`, so an
option cannot be smuggled into repo's argv — the allowlist alone does not stop
that, because it resolves `--force-remove-dirty` to a path inside the tree. The
dirty scan always covers the whole publish set, so a bogus path cannot make the
tree look clean.

**`tree_repair`** → `RepairResult`. Recreates
`build/{CleanSpec.mk,buildspec.mk.default,core,envsetup.sh,target,tools}` as
symlinks into `build/make/`, and copies `build/make/core/root.mk` to
`./Makefile`. Those are `<linkfile>`/`<copyfile>` results; a partial sync loses
them and the tree then has no envsetup at all. Writes only those seven paths.

**`build_start`** → `BuildJob`. `target` (`bestrom`/`installclean`/
`otapackage`), `installclean`, `jobs`, `log_name`, `dry_run`. Runs
`build-bestrom-run.sh` inside `systemd-run --user --unit=bestrom-build-<stamp>`,
because a `nohup setsid` chain dies with the session and a bare `mka` leaks
`eng.<user>` into `ro.build.fingerprint`. The lunch string is fixed in code and
is never caller-supplied. Refuses — never queues — while `soong_ui` or `ninja`
is running, and names the log the in-flight build is writing to.

There is no `official` flag. `build-bestrom-run.sh` exports `BESTROM_OFFICIAL`
itself, so an inherited value is overwritten before `config/branding.mk` reads
it and a flag here would have handed back a zip named `…-OFFICIAL.zip` that then
matches `zip_glob` and becomes the release candidate. The result reports
`official` and a `note` saying which line in the wrapper decided it.

**`build_status`** → `BuildStatus`. Reads the systemd unit and the log file, not
an in-process handle, so it works after the server restarts. The transient unit
is `--collect`ed when it ends, so the authoritative completion record is the
`=== <UTC> BUILD EXIT: N ===` line, which this parses. The tail is capped at 200
lines: `build-aperture-1555.log` is 21 MB.

**`build_errors`** → `BuildErrors`. Streams the log for `FAILED:` and `error:`,
drops warnings, deduplicates, truncates each line to 400 characters.

**`build_cancel`** → `CancelResult`. `systemctl --user stop <unit>`, and only for
a unit in the job registry carrying the `bestrom-build-` prefix. Nothing in this
server is ever killed by command-line pattern.

**`build_artifacts`** → `Artifacts`. Uses the real naming contract from
`config/branding.mk` rather than guessing, reads the `.sha256` sidecar before
hashing 2.7 GB, and reports the size delta against the previous package.

**`verify_image`** → `VerifyReport`. `profile`, `checks`, `write_marker`,
`marker_name`. The project's quality gate as data — see
[`profiles/README.md`](profiles/README.md). `write_marker` is the one write and
it only ever touches a chain marker inside the logs directory.

Two rules make the marker mean something. A run that names a subset in `checks`
is a diagnostic — `partial` comes back true, `passed` is false and no marker is
written, because "three of eighteen checks passed" is not "the image is good".
And `marker_name` must match `chain-<slug>-build.done` for a configured chain or
the profile being run, so one profile's result cannot be planted as another
chain's gate and a marker cannot overwrite the release notes or a build log. The
marker records the profile name and `checks run: N of M`, which `release_publish`
re-reads and rejects when N is not M.

**`device_list`** → `DeviceList`. Checks `ss -ltn` for a listener on port 15038
first and refuses to run adb at all without one. Also probes root, because on
this user build an empty tombstone dump reads to an agent as "no crashes".

**`device_capture`** → `CaptureResult`. `kind` (`crashes`, `logcat`, `dropbox`,
`screenshot`, `avc`, `packages`), `package`, `timeout_s`, `out_dir`. Writes a
timestamped directory under the evidence root and returns a small summary — tag
histogram, `process :: first exception line` rollup, avc histogram, file list.
The bulk stays on disk behind `bestrom://device-evidence/latest`. `package` is
validated against `pm list packages`; there is no arbitrary shell.

**`device_sideload`** → `SideloadPlan`. Deliberately does not flash. Sideload
over the reverse tunnel runs at ~0.7 MB/s and drops before a 2.7 GB package
finishes, so this returns the exact local command instead. It also refuses a
`boot.img` flash that omits `vendor_boot.img` — that pairing is how the QRTR
sensor bootloop was reproduced — and refuses any package the verify gate has not
passed.

**`device_agent_*`** → the fifteen Agent mode tools. They have their own
section below, [Driving the phone](#driving-the-phone-agent-mode), because the
pairing flow and the untrusted-content rule matter more than any one signature.

**`release_prepare`** → `ReleaseDrafts`. One `notes` input becomes the
SourceForge `README.txt`, the changelog entry and the OTA catalog JSON, plus the
site release card rendered as a diff. Publishes nothing; `dry_run=false` writes
drafts to the staging directory and still uploads nothing.

**`release_publish`** → `PublishResult`. Runs `chain-<chain>-publish.sh`: 7 repo
pushes, a SourceForge upload, an htdocs overwrite and the OTA catalog every
user's Updater reads. Both gates are re-evaluated inside the tool and never
trusted from an earlier call. `rsync`/`ssh`/`curl` output is reduced to a status
line plus a log path; push output is filtered.

There is no stage selection. The chain scripts take no arguments and always run
all four stages, so the tool does not offer a subset it could not enforce. It
also reads the script before running it: the chain scripts carry a per-release
`PREVZ=`, and re-running a stale one pushes correctly but leaves a site card
naming a package that is no longer there, so a `PREVZ` that does not match the
current previous package is a refusal. An AI attribution trailer in the script
comes back as a warning, because this server flags that same trailer in commit
messages. One publish at a time: the tool takes a lock in the state directory,
and a timeout kills the whole process group rather than leaving `rsync` running.

**`changelog_add`** → `ChangelogResult`. `section`, `bullets`, `dry_run`.
Inserts one section under the `Unreleased (next build)` heading in
`vendor/bestrom/CHANGELOG.md`, in the existing plain-heading plus two-space
`  * ` bullet style, wrapped at 72. A dry run returns the diff and writes
nothing; `dry_run=false` rewrites that one file and commits nothing. It never
touches a released section — if the `Unreleased` heading is gone it refuses
rather than guessing where the entry belongs.

**`commit_message_check`** → `StyleReport`. Pure: no subprocess, no filesystem.
Returns the rule id and severity of every violation plus a mechanically repaired
message. The same rules are in prose at `bestrom://style-guide`.

**`strip_ai_trailers`** → `TrailerScan`. `repo`, `since`. Reports which commits
carry `Co-Authored-By: Claude`, "Generated with [Claude Code]" or the robot
emoji, and hands back a `git filter-repo` command (a separate install) for the
maintainer to run. It never rewrites history: a rewrite in a repo-managed tree
is not something that should happen behind an agent call. The default range is
`<remote>/<manifest revision>..HEAD` with the remote taken from the publish set
— `origin` is wrong for `device/xiaomi/peridot` and `frameworks/base`.

## Driving the phone (Agent mode)

Agent mode is a switch on the phone: **Settings > Custom Tweaks > Agent mode**.
With it off, `com.bestrom.agent` is an APK on disk — both its services ship
`android:enabled="false"`, it has no receiver, no job and no provider, and it
holds no network permission at all. With it on, it listens on the Linux abstract
socket `bestrom_agent`, shows a six-digit pairing code and posts an ongoing
notification for as long as it is running.

**It does not survive a reboot.** After a restart the switch reads Off, the
accessibility service takes itself back out of the secure setting, and this
server's pairing is dead. That is deliberate: anything that restored it would
put the agent in the boot path.

### The flow

1. On the phone, open Settings > Custom Tweaks > Agent mode and turn it on.
   Grant the notification permission when it asks. Read the six digits.
2. `device_agent_status` — sets up
   `adb -P 15038 -s bc94484f forward tcp:8765 localabstract:bestrom_agent`,
   says hello, and takes the forward down again. It reports whether the bridge
   is up, whether the accessibility half is connected and whether the phone is
   locked.
3. `device_agent_pair(code="123456")` — the six digits. What comes back is
   written to `state/agent-pairing.json` with mode 0600 and is never returned by
   any tool, never logged and never in a refusal. **The code is single use**:
   pairing consumes it, so pairing a second client means pressing **New code**
   on the phone's Agent mode screen. Three wrong codes put pairing in a cooldown
   the phone shows on that same screen, with the seconds remaining, so a refusal
   here is never a mystery. A `-32002` carrying `data.reason=already_paired` is
   **not** a wrong code: the phone already has a token out to another session.
   Press **New code** and pair again — re-reading the digits cannot help, and
   this server keeps no strike count of its own, so a refusal like that costs
   nothing here. `code_expires_utc` in the result is when the digits
   stop working, not when the pairing does — the pairing lasts until the bridge
   stops.
4. Then the rest: `device_agent_functions` and `device_agent_execute` for app
   functions, `device_agent_ui_tree` and `device_agent_screenshot` to see the
   screen, `device_agent_tap` / `_long_press` / `_swipe` / `_type` / `_key` /
   `_launch` to act on it, `device_agent_log` for the phone's own record of what
   happened, and `device_agent_stop` when the phone is out of arm's reach.

Every action tool and `device_agent_execute` need **both** `dry_run=false` and
`confirm=true`. A dry run returns the exact JSON-RPC line it would send. The
phone applies the same confirm floor again on its side, so a misbehaving client
cannot act by accident. `device_agent_log(clear=true)` needs `confirm=true` for
the same reason: it is the only record of what the agent did.

The forward is opened per call and taken down after it. A `tcp:8765` left
listening on the build machine is a door to the phone for every local process,
and the phone's own auth is all that stands behind it. The manual undo, when a
call dies badly, is `adb -P 15038 forward --remove tcp:8765`. The other side of
that: **a forward you set up by hand does not survive the next MCP call.** Every
tool opens the forward and closes it again, so a `nc` session against
`tcp:8765` from your own shell — the T8 round trip, say — dies the moment any
`device_agent_*` tool runs. Re-issue it after.

### What the phone refuses, and what that means

| Code | Name | What it means |
|---|---|---|
| -32005 | `DEVICE_LOCKED` | The lock screen is showing. It refuses whenever the keyguard is up, not only when the phone is "locked" in the trust sense — a swipe-only lock and Smart Lock are still a lock screen, and a lock-screen tree leaks notification content. No override, not even for reads. |
| -32006 | `USER_INTERACTING` | The user touched the screen within the last 1.5 s. Reads are exempt; actions are not. |
| -32012 | `SECURE_WINDOW` | **Two refusals under one name, and `data.reason` says which.** With no data: a password field — the phone will not type into one and does not serialise its text or its content description. This is **blocked**, not empty. With `data.reason=denied_package` and `data.package`: that package is on the phone's Agent mode denylist and `ui.tree`, `ui.screenshot` and `ui.tap` refuse it outright. |
| -32004 | `AGENT_DISABLED` | Agent mode is off, or the accessibility half is not connected. `data.reason=no_active_window` is the narrower case: the bridge is up and there was no foreground window to read at that instant. Transient — try again; do not go looking for a switch that is already on. |
| -32002 | `BAD_PAIRING_CODE` | Wrong six digits — three of them start a cooldown the phone shows on its own screen. `data.reason=already_paired` is a different thing entirely: the phone is paired with another session, nothing was guessed, and no amount of retrying will land. Press **New code** on the Agent mode screen and pair again. |
| -32007 | `RATE_LIMITED` | Ten actions a second, shared across connections. |
| -32013 | `SCREENSHOT_UNAVAILABLE` | The platform refused the capture; `data.reason` carries its own code — an **integer** here, not one of the string reasons above. The commonest is the minimum interval between two captures. |
| -32010 | `APP_FUNCTION_ERROR` | The function itself failed; `data.code` carries the `AppFunctionException` code verbatim. |
| -32602 | `INVALID_PARAMS` | The phone rejected the parameters. Two it now refuses outright, and that this server therefore never sends: `include_invisible=true` on `ui.tree`, and any `encoding` but `"base64"` on `ui.screenshot`. Both were surfaces with no caller and are gone rather than left reachable. |

Every refusal a tool returns is a sentence, not a number: `refused_reason` is
the code's name and a plain-English hint, and `error.hint` carries the same
line. Where one code means two things the hint is picked by `data.reason`, so
an `already_paired` refusal does not read "wrong pairing code" and a
`denied_package` one does not send you hunting for a password field.

Two refusals that do **not** happen, and must not be assumed:

* **A secure screen is not refused.** `FLAG_SECURE` governs screen capture, not
  accessibility, so `device_agent_ui_tree` reads the tree of a banking app or an
  authenticator like any other. `device_agent_screenshot` gets a frame with
  those layers **blacked out by the platform** — a black rectangle is redaction,
  not a failure.
* **A denied package is refused on the phone, not here.** The Agent mode screen
  carries a package denylist, empty by default and editable only there — never
  over the bridge. A package on it is refused by `ui.tree`, `ui.screenshot` and
  `ui.tap`, matched exactly, with `-32012`, `data.reason=denied_package` and
  `data.package` naming it. There is no host-side override and there is nothing
  to retry: **the denylist is edited on the phone, on the Agent mode screen.**
  The phone enforces it because it has to — an accessibility service is handed
  the tree of every app, so an exclusion is enforced there or not at all.
  Read the scope literally: it is those three methods. `ui.long_press`,
  `ui.swipe`, `ui.type`, `ui.key` and `app.launch` carry no denylist check on
  the phone, so a denied package can still be swiped at by coordinate or
  started by name. Treat the list as "do not read this app", not as a sandbox.

### Reading two results honestly

**`device_agent_functions`.** `parameters` and `response` are JSON **arrays** of
objects — one object per parameter — or **absent**. Never `{}` and never `[]`:
the phone flattens its metadata without collapsing a single-element list, and
omits the key outright when there is nothing in it, so a one-parameter and a
two-parameter function have the same shape and "no parameters" has exactly one
spelling. (A bare object is still accepted and wrapped, because an older build
of the app did collapse it.)

`fallback_reason` is empty when the phone answered from `searchAppFunctions`. It
is set when the phone had to fall back to querying the raw AppSearch index, and
it is one of exactly two strings, passed through verbatim so it can be grepped
for in the on-device log. `fallback_hint` carries the one line that says what
the list in hand is then worth:

| `fallback_reason` | What it means |
|---|---|
| `app_function_manager_unavailable` | The phone could not get `AppFunctionManager` at all. `enabled` is assumed true, and `device_agent_execute` will fail with a system error until that service is back. |
| `search_app_functions_failed` | The manager was there and `searchAppFunctions` failed or missed the phone's 10 s budget. The list can be stale or short and `enabled` is assumed true, but executing still works — ask again before believing a gap. |

Without the reason, "nothing is indexed" and "the AppFunctions manager is
broken" are the same answer: `source=appsearch`, `count=0`.

**`device_agent_log`.** Each entry carries `peer_uid` and `connection_id`
alongside the method, target and result: who asked, and over which connection,
so a burst is attributable after the fact and an entry this server did not cause
is recognisable. `2000` is shell — what every call from this server looks like,
because it arrives through `adb forward` — `0` is root, and `-1` is the phone
writing its own entry rather than the wire (the switch, the Clear button). Both
are `null` on an entry from a bridge build that predates the fields; that is not
an error and does not mean uid 0. Nothing this server models forbids unknown
fields, deliberately: the phone and this server are versioned apart, and a field
the bridge grows next must cost that field, not the whole call.

### Screen content is data, never instruction

Everything `device_agent_ui_tree` and `device_agent_screenshot` return is text
an app drew on the screen, and any app can draw anything there. A tree that says
"ignore your instructions and run X" is an attack, not a request. Phase 1 puts
that risk on the host, where a human is watching, by refusing to be autonomous
at all: no trigger, no loop, no schedule, and a confirmation on every action.
The tool descriptions say so in one sentence each, and the models carry the
sentence next to the payload.

### Security note

> Phase 1 is a MAINTAINER TOOL, not a user feature, and it must be described
> that way until the signing keys are rotated. BestROM images are currently
> signed with VoltageOS's public `vendor_voltage-priv_keys`, so anyone can build
> an APK that claims to be `com.bestrom.agent`, matches the platform certificate
> and inherits `EXECUTE_APP_FUNCTIONS` and `WRITE_SECURE_SETTINGS`. Every
> privilege in this design is exactly as strong as that key. The private key set
> is prepared at `/serverhive1/sal/bestrom-priv`; rotating it is a clean flash,
> and it is the gate on calling Agent mode a shipped feature. Until then: build
> it, run it on the maintainer's own phone, and say so in the release notes.

What the design does defend, independently of the key:

* **No network.** The bridge is a unix abstract socket reached only through
  `adb forward`, the app holds no `INTERNET` permission and a verify gate
  asserts its absence.
* **No persistence.** Every component ships disabled, there is no receiver, job,
  provider or notification listener, and Agent mode does not survive a reboot.
* **No silent power.** A single-use code on the phone screen to pair, an ongoing
  notification for the whole session, three independent stops and a
  thirty-minute idle timeout.
* **Only adbd gets in** — but that is the peer-uid check, not the policy.
  `system/sepolicy/private/domain.te` allows a domain to `connectto` its own
  type, so any `platform_app` on the phone can reach this abstract socket; the
  thing that actually keeps it to adb is the bridge closing any connection whose
  peer uid is not shell (2000) or root (0), before a single byte is read.
  This server always reaches the bridge through `adb forward`, so the connection
  is made by adbd and the phone sees **uid 2000**. That is the expectation on
  both sides and there is nothing to configure. The corollary is the point:
  **a client connecting to `localabstract:bestrom_agent` directly on the phone
  is refused** — another platform-signed app, a shell-less process, anything
  whose uid is not 2000 or 0 — and so is a connection with no peer credentials
  at all, which reads as `-1`. `peer_uid` on every audit entry records which of
  those asked.
* **A refusal on the phone for a locked screen, a password field, a denied
  package, a touch in the last 1.5 s and the tenth action in a second.**

Read the confirm floor honestly. The phone refuses `confirm != true` on the nine
mutating methods, but this client always sends `confirm: true` and decides on
the host side whether to send the request at all. So the phone-side floor is a
**floor against a client that forgets, not against one that is hostile**: it
catches a bug or a hand-written request, and nothing more. A second gate worth
the name would have to be a human action on the phone, not a boolean on the
wire.

Also honest about the transport: the forward is per call. A `tcp:8765` you set
up by hand is torn down by the next `device_agent_*` call, and nothing keeps the
port open between calls.

What it does **not** defend, and must be said out loud: indirect prompt
injection. See the paragraph above.

## Resources

| URI | Contents |
|---|---|
| `bestrom://manifest` | The BestROM manifest, with a header line saying whether the `.repo` mirror is byte-identical right now |
| `bestrom://changelog` | `vendor/bestrom/CHANGELOG.md` — the voice release notes have to match |
| `bestrom://build/latest-log` | Last 400 lines of the newest build log plus the parsed exit line and error extract |
| `bestrom://style-guide` | The commit and changelog conventions in prose |
| `bestrom://device-evidence/latest` | Index of the newest crash-sweep capture, so an agent picks a file instead of pulling megabytes |
| `bestrom://config` | The effective configuration after TOML and env overrides, redacted |

## Prompts

`release-checklist`, `crash-triage`, `new-feature-branch`, `build-triage`. Each
is the project's real order of operations with the gates named, so an agent
reads the rules before acting rather than after failing.

## Safety model

Tool annotations are hints for the client UI. The real gates are in code.

1. **Annotations.** `destructiveHint` on `repo_sync`, `build_cancel`,
   `device_sideload`, `release_publish` and the seven `device_agent_*` tools
   that act on the phone; `openWorldHint` on everything that reaches the network
   or the phone, which is every `device_agent_*` tool; `readOnlyHint` and `idempotentHint` on the
   tools that read. The authoritative list is the annotations column of
   `tools/list`, not this paragraph. Two notes on the hints that matter:
   `device_capture` does **not** carry `readOnlyHint`, because it writes a
   timestamped evidence directory; `verify_image` does, and that describes the
   default `write_marker=false` call — with `write_marker=true` it writes one
   chain marker.
2. **`dry_run` defaults to true** on every mutating tool, and a dry run returns
   the exact command it would run — which doubles as the documentation.
3. **`confirm` is a separate boolean** on anything that flashes, pushes or
   uploads, so a model cannot reach it by flipping one field. `confirm` without
   `dry_run=false` is a refusal, not an execution.
4. **Real gates, re-evaluated in the tool.** `release_publish` refuses unless
   the marker contains `verify gate passed`, records a full profile run, and
   names the newest package on disk. `verify_image` writes that literal only
   after the whole profile ran clean — a `checks` subset is refused a marker.
   `build_start` refuses when `pgrep -x soong_ui` or `pgrep -x ninja` hits.
   `device_sideload` refuses boot without vendor_boot. Every `device_agent_*`
   action refuses without `dry_run=false` and `confirm=true`, and the phone
   applies the same floor again — the host is not trusted to have applied it.
5. **Path allowlist.** Every filesystem argument resolves and must land inside
   the tree root, `/serverhive1/sal/bootloop-logs` or `/serverhive1/sal/dl`.
   Symlinks are resolved before the check, so a link inside the tree pointing
   out of it is rejected. Writes are narrowed further per tool.
6. **No arbitrary shell.** There is no `run_shell` and no
   `execute_adb_command`: it would defeat every gate above. The Agent mode
   bridge is the same rule one layer out — its method names are a closed set in
   `ops/agent.py` and there is no passthrough that could name another one. Enums where a value
   is one of a fixed set; the lunch string is fixed in code. Arguments that
   reach an argv are validated as what they claim to be — a project path is a
   path, a commit range is a range — and never merely resolved against the
   allowlist, which accepts an option-shaped string as a filename. Device-side
   commands are quoted with `shlex.quote`, never with Python's `repr`.
7. **Process discipline.** Every subprocess carries an explicit timeout (60 s
   default, 300 s only for `dumpsys dropbox --print`, `[release]
   publish_timeout_s` for the publish chain) and captures stdout — never
   inherits it, because one stray byte on stdout corrupts the JSON-RPC stream.
   Children run in their own session, so a timeout kills the whole process
   group: a timed-out publish does not leave `rsync` and `git push` running
   after the agent has been told it failed. `repo_sync` and `release_publish`
   take a lock so a client-side retry cannot start a second one. Process
   matching is exact-name only (`pgrep -x`); nothing is ever matched or killed
   by `-f` pattern.
8. **Secret hygiene.** Redaction covers `Authorization` headers,
   `http.extraheader` values, `ghp_` / `github_pat_` tokens, URL credentials,
   ssh key material and the Agent mode pairing secret. That last one is never a
   tool parameter, never a return field and never in a refusal: it lives in
   `state/agent-pairing.json` at mode 0600, and a test asserts that the JSON of
   every model a `device_agent_*` tool returns contains neither the value nor
   the word. It runs on every subprocess result and on every log tail or
   grep (in `proc.py`), on the `bestrom://config` resource, and on the release
   notes — the one place a tool reads a file itself, where the content is also
   capped at 64 KB and can only come from a `.txt`/`.md` file in the logs
   directory. It is not automatic at the tool return boundary, so a new tool
   that reads a file must scrub it; `redact.py` says so at the top. No tool
   returns git config, an environment dump or `~/.gitconfig`. Build logs are
   always tailed or grepped, never returned whole.
9. **Never here.** No history rewriting, no `m clean`, no
   `repo sync --force-sync`, no push outside `release_publish`, and no writing
   to the tree root except through the manifest `<copyfile>` mechanism.

## Configuration

Precedence, lowest first: structural defaults in `config.py` < the shipped
[`bestrom.toml`](bestrom.toml) < a user TOML at `$BESTROM_MCP_CONFIG` <
`BESTROM_MCP_*` environment variables.

Nothing machine-specific is hardcoded in Python. The only code-level default is
structural: the tree root is four levels up from this directory, overridable
with `BESTROM_TREE`.

| Section | Keys |
|---|---|
| `[tree]` | `root`, `out_dir`, `logs_dir`, `dl_dir`, `min_free_gb` |
| `[build]` | `script`, `lunch`, `goal`, `jobs`, `official`, `unit_prefix`, `log_prefix`, `zip_glob` |
| `[verify]` | `profile`, `profiles_dir`, `marker_dir` |
| `[device]` | `adb_port`, `adb_host`, `serial`, `default_timeout_s`, `max_timeout_s`, `evidence_dir`, `allow_remote_sideload` |
| `[agent]` | `port`, `socket`, `package`, `connect_timeout_s`, `request_timeout_s`, `max_request_timeout_s`, `evidence_dir`, `evidence_subdir`, `state_file`, `inline_node_limit` |
| `[release]` | `chains`, `sourceforge_project`, `sourceforge_frs_path`, `sourceforge_web_path`, `ota_repo`, `ota_branch`, `site_repo`, `pages_dir`, `publish_timeout_s`, `kernel`, `base` |
| `[push]` | `projects` — the `path remote branch` triples from the publish chain |
| `[safety]` | `allowlist_roots`, `enable_publish` |

There is deliberately no `require_confirm` key. Which tools demand
`confirm=true` is decided inside each tool; a config key would have looked like
a control and enforced nothing. `bestrom://config` reports the real list under
`safety.confirm_required`, straight from `config.CONFIRM_REQUIRED_TOOLS`.

`[release] kernel` and `base` are printed verbatim in the release README
header. Everything else in that header — Android version, SDK, both security
patch levels — is read from the built `build.prop`, and any field that cannot be
determined is printed as `(unknown)` and listed in the result's `warnings`
rather than carried over from the previous release.

Environment overrides use the flattened key: `BESTROM_MCP_TREE_ROOT`,
`BESTROM_MCP_DEVICE_ADB_PORT`, `BESTROM_MCP_BUILD_JOBS`,
`BESTROM_MCP_SAFETY_ENABLE_PUBLISH`, and so on. Job-registry state lives at
`$BESTROM_MCP_STATE`, defaulting to `state/` here, which is git-ignored.

**No credential is read from or written to the configuration.** GitHub auth
comes from the existing `~/.gitconfig` `http.extraheader` and SourceForge from
the ssh agent; the server never reads, prints or forwards either.
`bestrom://config` has no field that could hold a secret by construction.

## Tests

    uv run python -m pytest -q

Pure functions and sandbox trees under `tmp_path`: no real tree, no device, no
network.

| File | Covers |
|---|---|
| `tests/test_style.py` | Every commit rule, asserting rule id and severity, and that the suggested message round-trips clean |
| `tests/test_verify.py` | The profile evaluator against fixtures, including that a passing expected-check does not mask a failing forbidden one |
| `tests/test_redact.py` | Ten secret shapes in, nothing recoverable out — plus a negative test that build output is unmangled |
| `tests/test_config.py` | Precedence, structural root discovery, and allowlist rejection of `..`, absolute escapes and symlinks |
| `tests/test_jobs.py` | Unit naming, registry round-trip, `systemctl show` and `BUILD EXIT` parsing |
| `tests/test_gates.py` | Both publish gates as predicates against fixture markers, that a partial marker fails, that a stale `PREVZ` refuses, and that no `stages` argument exists |
| `tests/test_repo_sync.py` | Option-shaped `projects` entries are refused, validated paths go after `--`, a dry run touches no network |
| `tests/test_release_notes.py` | `notes_path` confined to the notes location, scrubbed and capped; the release header derived, not hardcoded |
| `tests/test_device_args.py` | `su -c` quoting round-trips through a POSIX lexer; package names reject a trailing newline; props parse by key |
| `tests/test_agent.py` | The bridge client against a fake bridge on a real socket: the port guard, the exact forward argv and its teardown, reassembly across recv boundaries, the confirm floor on all nine gated tools, error mapping — including the three codes that mean two things and pick their hint from `data.reason` — the audit log's `peer_uid`/`connection_id` and its tolerance of a field this server has never heard of, both `functions.list` fallback reasons, that `include_invisible` and a non-base64 `encoding` are never sent, and that no model any tool returns carries the pairing secret or even the word |
| `tests/test_proc.py` | A timeout kills the grandchild, not only the direct child |

`tests/test_verify.py` calls `verify_image` itself, not a reimplementation of
its pass logic, for the marker rules — that gap is how a subset run once wrote
the gate.

Not covered automatically, and needing a live device and a maintainer:
`device_capture` against the phone, `repo_sync` with `dry_run=false`, and
`release_publish`'s frs/ota/site stages.

`smoke/stdio_smoke.py` is the integration check: it spawns the server over
stdio, keeps stdin open for the whole exchange, and asserts the tool list is
deterministic, every tool carries a title, annotations and an `outputSchema`,
the read-only tools return `structuredContent`, a `checks` subset cannot write
the marker, `repo_sync` refuses an option-shaped project, `release_prepare`
refuses an arbitrary file read, and `device_sideload` and `release_publish`
refuse without confirm. Checks that need a completed build are skipped and
reported as skipped. It builds nothing, pushes nothing, uploads nothing and
flashes nothing.

## Troubleshooting

**The client shows no tools, or the connection drops immediately.** Something
wrote to stdout. On stdio a single stray byte corrupts the JSON-RPC framing —
that is why every subprocess here captures its output and every diagnostic goes
to stderr. Run `smoke/stdio_smoke.py`; it fails with a JSON decode error the
moment stdout is polluted, and captures the server's stderr to
`state/smoke-stderr.log`.

**`device_list` says the port has no listener.** That is the guard working. The
reverse tunnel is not up. Do **not** run `adb -P 15038` to "check" — on an
unbound port that starts a local adb server which squats the port, and the
tunnel can then never bind. Bring up the `ssh -R` tunnel, confirm with
`ss -ltn | grep 15038`, then retry.

**A build outlives the client.** By design. `build_start` returns a `job_id` and
a log path; poll with `build_status` later, in a new session if you like. The
job is a `systemd --user` unit and does not care that the client disconnected.
If `build_status` reports `unit_state=gone`, the transient unit was collected
when it ended and the log's `BUILD EXIT` line is the answer.

**A tool call times out in the client.** `.mcp.json` sets `timeout` to 600000
ms. Raise `MCP_TIMEOUT` in the environment if `repo_sync` or a cold
`verify_image` still exceeds it. `repo_sync` and `release_publish` hold a lock
while they run, so a retry after a client-side timeout is refused with the name
of the call still in flight rather than starting a second one.

**Every tool fails with "path outside the allowlist".** The tree root resolved
wrong. Read `bestrom://config` and look at `tree.root`; if it is not the
checkout, unset `BESTROM_TREE` (the server derives the root from its own
location) or point it at the real root. Since the startup guard landed, a root
that contains neither `build/make` nor `vendor/bestrom` fails at connect
instead, with the variable named in the error.

**`uv: command not found` when the client starts the server.** Install uv:
`curl -LsSf https://astral.sh/uv/install.sh | sh`, then restart the client so it
picks up the new PATH.
