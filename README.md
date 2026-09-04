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

## Use

The device makefile sets `BESTROM_DEVICE` and inherits `config/branding.mk`.
Build with `mka bestrom`, not `mka bacon` — `bacon` is VoltageOS's target and
produces a `voltage-*.zip`.
