# AGENTS.md — BestROM (POCO F6 "peridot", Android 17)

<!--
  SOURCE OF TRUTH: vendor/bestrom/tools/AGENTS.md
  The copy at the tree root is written by repo <copyfile> on every sync.
  Edit it here or your edit is lost the next time anyone runs `repo sync`.
  Keep this file under 200 lines: it is loaded into every agent's context.
-->

This file tells an AI agent how to work in this tree. It follows the
[agents.md](https://agents.md) convention. Humans should read it too.

## What this is

BestROM is an Android 17 ROM for the Xiaomi POCO F6 / Redmi Note 13 Pro+ 5G
(codename `peridot`, SoC sm8635). It is a **product layer on top of
VoltageOS 6.1**, not a fork of AOSP: `vendor/bestrom` adds BestROM identity and
`vendor/voltage` supplies the base product configuration.

This checkout is a `repo`-managed tree. The BestROM manifest lives at
`vendor/bestrom/manifest/bestrom.xml` and is mirrored to
`.repo/local_manifests/bestrom.xml`; the two must stay byte-identical.

## Use the MCP server

Everything below is exposed as tools by the BestROM MCP server at
`vendor/bestrom/tools/mcp/`. Prefer the tools over ad-hoc shell: they carry the
gates, the timeouts and the redaction that the raw commands do not.

It needs Python 3.11+ and `uv`
(`curl -LsSf https://astral.sh/uv/install.sh | sh`). Nothing else: the root
`.mcp.json` runs `uv run --directory vendor/bestrom/tools/mcp bestrom-mcp`,
which creates the venv on the first connection. To do it by hand:

    cd vendor/bestrom/tools/mcp && uv sync

See `vendor/bestrom/tools/mcp/README.md` for the tool reference and for the
Cursor and Codex client entries.

Run `env_check` before anything expensive. It catches the two failures that
waste hours: no disk headroom, and a build already in flight.

## Building

    bash build-bestrom-run.sh          # MCP: build_start

Rules:

* That wrapper is the build. It exports `BUILD_USERNAME`, `BUILD_HOSTNAME`,
  `BUILD_NUMBER` and `BESTROM_OFFICIAL`, which end up in
  `ro.build.fingerprint`. A bare `mka` leaks `eng.<user>` into the fingerprint,
  so `source build/envsetup.sh; lunch bestrom_peridot-cp2a-user; mka <module>`
  is for building a single module and for inspection only, never for a package.
* It exports `BESTROM_OFFICIAL=true` unconditionally, so every build through it
  is stamped OFFICIAL. Change that line to `${BESTROM_OFFICIAL:-true}` first if
  you want a throwaway build that cannot be mistaken for a release.
* `mka bestrom`, never `mka bacon`. `bacon` is VoltageOS's target and emits a
  `voltage-*.zip`; `bestrom` is `vendor/bestrom/build/tasks/bestrom.mk`.
* The package lands in `out/target/product/peridot/` as
  `BestROM-<ver>-peridot-<date>-<time>-<OFFICIAL|UNOFFICIAL>.zip`, with a
  `.sha256` sidecar beside it once the publish chain has run.
* The build log goes to the configured logs directory (`[tree] logs_dir` in
  `vendor/bestrom/tools/mcp/bestrom.toml`, currently
  `/serverhive1/sal/bootloop-logs/`) as `build-<name>-<HHMMSS>.log`.
  `build_status` returns both paths; so does the dry run of `build_start`.
* The build's completion contract is the line
  `=== <UTC> BUILD EXIT: <rc> ===` in that log. Parse that, not the exit status
  of whatever launched it.
* A build takes 1-3 hours. Launch it detached (`systemd-run --user`, which is
  what `build_start` does) — `nohup setsid` chains die with the session.
* `m installclean` is required when the product configuration changed, e.g. a
  package was removed: stale staged files under `out/.../system/priv-app/` are
  otherwise packaged into the zip. A full `m clean` throws away ~141 GB of
  `out/` and is almost never the right answer.
* After a partial sync, `build/envsetup.sh` and `./Makefile` can be missing —
  they are `<linkfile>`/`<copyfile>` results from `build/make`. Recreate them
  (MCP: `tree_repair`) instead of re-syncing.

## Verifying an image

A build that succeeds is not a build that is correct. Before anything ships,
the image is checked against a declarative profile
(`vendor/bestrom/tools/mcp/profiles/peridot.toml`, MCP: `verify_image`).

The profile keeps an **expected/forbidden symmetry**: every "this must be
present" check is paired with a "this must be absent" check. A presence-only
gate passes a broken image — that is exactly how a build shipped with both the
old and the new camera staged in `out/`. Do not add a check without its
opposite.

`verify_image` writes the literal string `verify gate passed` into the build
marker, and only after the whole profile ran clean. Running a subset with
`checks` is a diagnostic: it is refused a marker, and the marker records how
many checks ran so a partial one cannot pass the publish gate later. The
publish chain refuses without the literal.

## The phone

Serial `bc94484f`, reached over a reverse SSH tunnel on port **15038**.

* Always `adb -P 15038`. **Never** run `adb` on that port before `sshd` has
  bound it — `adb -P` on an unbound port silently starts a local adb daemon
  that squats the port, and the tunnel can then never bind. Check
  `ss -ltn | grep 15038` first. `device_list` does this for you and refuses
  rather than guessing.
* It is a **user build with no adb root**. `/data/tombstones` and root-gated
  dumps come back empty. Empty output is not evidence of no crashes; say so.
* SELinux is enforcing. Do not propose `setenforce 0` as a fix.
* Do not sideload a 2.7 GB zip over the tunnel: it runs at ~0.7 MB/s and drops.
  `device_sideload` refuses and prints the local command for the maintainer.
* Never flash `boot.img` without `vendor_boot.img`. Flashing one alone is how
  the QRTR bootloop was reproduced.
* Evidence goes to the configured evidence directory (`[device] evidence_dir`
  in `vendor/bestrom/tools/mcp/bestrom.toml`, currently
  `/serverhive1/sal/bootloop-logs/crash-sweep/`), one timestamped directory per
  capture, never overwritten.

## Never push

Agents do not push. Pushing, uploading to SourceForge, and updating the OTA
catalog (which reaches every user's Updater) happen only through the publish
chain, and only behind two gates that are re-checked at publish time:

1. the build marker contains `verify gate passed`, and
2. the newest zip on disk is the same filename the marker recorded.

Do not rewrite git history. If AI attribution needs stripping, report the
commits and hand the maintainer the command; the rewrite is theirs to run.

## Tree conventions

* New files for this work belong under `vendor/bestrom/`. Root-level files
  (`AGENTS.md`, `CLAUDE.md`, `.mcp.json`) are **copies** produced by
  `<copyfile>` from `vendor/bestrom/tools/`. Editing a root copy in place loses
  the edit on the next sync.
* When you add a project to the manifest, add it to both copies and keep them
  identical (MCP: `manifest_check`).
* Do not add `hardware/qcom-caf/*`, `vendor/qcom/opensource/*`,
  `device/qcom/sepolicy_vndr/sm8650`, `hardware/xiaomi`,
  `hardware/google/pixel` or `hardware/nxp/*` to the BestROM manifest —
  VoltageOS's manifest already has them and repo rejects duplicate paths.
* `vendor/bestrom` is often on a feature branch while the manifest tracks
  `voltage-17`, and a commit on the wrong branch never reaches a build. Check
  the branch before committing (MCP: `repo_status` reports the current value
  against the manifest revision).

## Commit style

LineageOS style. The history is read by humans.

    vendor: Add the BestROM MCP server

    Wraps the build, verify, device and release chains as MCP tools so an
    agent can drive them without ad-hoc shell. Read-only by default; the
    mutating tools take dry_run and a separate confirm.

Rules (MCP: `commit_message_check`):

* Subject `area: Sentence-case summary`, where `area` is a real path prefix in
  the tree (`vendor`, `device`, `frameworks/base`, `sepolicy`, `docs`, …).
* Subject <= 50 characters preferred, 72 hard. No trailing period.
* Blank second line. Body 1-6 lines, each <= 72 characters.
* Plain English. No emoji. No AI vocabulary — no "comprehensive", "robust",
  "seamless", "leverage", "delve", "cutting-edge", "enhance the experience".
* No invented trailers, no `Generated with`, no `Co-Authored-By: Claude` in the
  ROM repos.
* Say what changed and why. The diff already says how.

## Do not

* Do not run a full build to test a one-line change; build the module.
* Do not return a 21 MB build log into context. Tail it or grep it.
* Do not print `~/.gitconfig`, tokens, `Authorization` headers or ssh keys.
  GitHub auth lives in `http.extraheader`, SourceForge in the ssh agent.
* Do not use `pkill -f` or `pgrep -f`. Exact names only (`pgrep -x ninja`), or
  stop the systemd unit by name.
* Do not add a `run_shell` escape hatch to the MCP server. It would defeat
  every gate above.
