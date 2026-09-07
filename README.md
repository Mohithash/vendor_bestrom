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

## Getting the source

```
repo init -u https://github.com/Mohithash/manifest -b 17 --git-lfs
repo sync -c -j$(nproc) --no-clone-bundle
. build/envsetup.sh && lunch bestrom_peridot-cp2a-user && mka bestrom
```

Every BestROM project lives under `github.com/Mohithash/<path_with_underscores>`
on branch `17`; the manifest is VoltageOS 17 plus `snippets/bestrom.xml`.

Two shipped binaries are built outside that namespace and outside the manifest.
Their corresponding source:

| Prebuilt | Source |
|---|---|
| `prebuilt/LeanType/LeanType.apk` (GPL-3.0) | https://github.com/Mohithash/LeanType branch `bestrom-17` — upstream `LeanBitLab/LeanType` tag `v4.2.0` plus one commit, also kept in `prebuilt/LeanType/patches/`. See [its README](prebuilt/LeanType/README.md) |
| `prebuilt/CromiteWebView/CromiteWebView.apk` (GPL-3.0 + Chromium BSD) | https://github.com/uazo/cromite at tag `v148.0.7778.168-cb3baf14f52eb4365d017f640f85310735c19b79`, the release asset unmodified. See [its README](prebuilt/CromiteWebView/README.md) |

## Contents

| Path | Purpose |
|---|---|
| `config/branding.mk` | `ro.bestrom.*` + `ro.modversion` in `/system/build.prop`, the overlay root, and `Updater` |
| `build/tasks/bestrom.mk` | `mka bestrom` — names the zip `BestROM-*.zip`. Auto-included by `build/make/core/Makefile:8146` |
| `overlay/common/…/SetupWizard` | Rebrands the only setup wizard in the tree |
| `overlay/common/…/Updater` | Repoints OTA at `Mohithash/bestrom_ota` |
| `bootanimation/generate.py` | Generator for a real BestROM animation; not wired up yet |
| `prebuilt/preinstall/` | Removable preloads (Via, MiXplorer) — copied to `/product`, installed on first boot by `BestromPreinstaller`. See [its README](prebuilt/preinstall/README.md) |
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
