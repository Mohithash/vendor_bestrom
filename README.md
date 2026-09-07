# vendor/bestrom

BestROM's product layer. It sits **on top of** `vendor/voltage`, which supplies
the base product configuration; this repository adds only BestROM identity.

It deliberately does **not** contain `config/common.mk`, `config/packages.mk`,
`build/tasks/bacon.mk` or `build/tasks/kernel.mk`. An earlier BestROM vendor
layer (branches `16`, `16.2`, `17`, `bestrom-a17`, `main`) did, because it was
written to replace a pure-AOSP product layer. Layering those over VoltageOS
breaks the build: two `PRODUCT_COPY_FILES` writing the same
`install/bin/backuptool.sh` is a hard error, a second `.PHONY: bacon` recipe
wins nondeterministically, and a competing `kernel.mk` fights VoltageOS's
`BoardConfigKernel.mk` chain.

## Contents

| Path | Purpose |
|---|---|
| `config/branding.mk` | `ro.bestrom.*` + `ro.modversion` in `/system/build.prop`, the overlay root, and `Updater` |
| `build/tasks/bestrom.mk` | `mka bestrom` — names the zip `BestROM-*.zip`. Auto-included by `build/make/core/Makefile:8146` |
| `overlay/common/…/SetupWizard` | Rebrands the only setup wizard in the tree |
| `overlay/common/…/Updater` | Repoints OTA at `Mohithash/bestrom_ota` |
| `bootanimation/generate.py` | Generator for a real BestROM animation; not wired up yet |
| `tools/AGENTS.md` | Agent instructions for the whole tree; copied to the tree root by `<copyfile>` |
| `tools/mcp/` | The BestROM MCP server: build, verify, device and release tools for AI agents |

## Use

The device makefile sets `BESTROM_DEVICE` and inherits `config/branding.mk`.
Build with `mka bestrom`, not `mka bacon` — `bacon` is VoltageOS's target and
produces a `voltage-*.zip`.

## Agent-ready

BestROM ships its own MCP server, [`tools/mcp/`](tools/mcp/), so an AI agent can
sync, build, verify the image, capture device evidence and prepare a release
through defined tools with real gates, instead of guessing at shell commands.
Nineteen tools, six resources and four prompts; every mutating one defaults to a
dry run and returns the exact command it would have run.

* [`tools/mcp/README.md`](tools/mcp/README.md) — the tool reference, the safety
  model and the configuration. Start here.
* [`tools/AGENTS.md`](tools/AGENTS.md) — how to work in this tree without the
  server: build commands, the verify gate, the adb port rule, the never-push
  rule, commit style.
* [`tools/mcp.json`](tools/mcp.json) — the Claude Code project-scope server
  entry; the same file carries the Cursor and Codex equivalents in its README.
* [`tools/mcp/profiles/`](tools/mcp/profiles/) — the image gate as data, with
  the expected/forbidden rule that catches a build shipping two cameras.

Requirements: Python 3.11+ and `uv`. There is no bootstrap step — the client
entry runs `uv run --directory vendor/bestrom/tools/mcp bestrom-mcp`, which
creates the git-ignored venv on the first connection. To do it by hand:
`cd vendor/bestrom/tools/mcp && uv sync`.

The tree-root `AGENTS.md`, `CLAUDE.md` and `.mcp.json` are **copies**, produced
by the `<copyfile>` entries on this project in `manifest/bestrom.xml`. Edit the
sources under `tools/`; a root copy edited in place is overwritten by the next
`repo sync`.
