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
   `device_sideload` and `release_publish`; `openWorldHint` only where the
   network or the phone is reached; `readOnlyHint` and `idempotentHint` on the
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
   `device_sideload` refuses boot without vendor_boot.
5. **Path allowlist.** Every filesystem argument resolves and must land inside
   the tree root, `/serverhive1/sal/bootloop-logs` or `/serverhive1/sal/dl`.
   Symlinks are resolved before the check, so a link inside the tree pointing
   out of it is rejected. Writes are narrowed further per tool.
6. **No arbitrary shell.** There is no `run_shell` and no
   `execute_adb_command`: it would defeat every gate above. Enums where a value
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
   `http.extraheader` values, `ghp_` / `github_pat_` tokens, URL credentials and
   ssh key material. It runs on every subprocess result and on every log tail or
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
