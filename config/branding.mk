#
# SPDX-FileCopyrightText: BestROM
# SPDX-License-Identifier: Apache-2.0
#
# BestROM product layer. This EXTENDS vendor/voltage; it must never duplicate
# what vendor/voltage/config/*.mk already sets. The previous BestROM vendor
# layer was written to replace an AOSP product layer and could not be used
# here: two PRODUCT_COPY_FILES writing the same install/bin/backuptool.sh is a
# hard build error, and a second ".PHONY: bacon" recipe wins nondeterministically.

# 3.0, not 1.0. The last shipped release was BestROM-2.0-peridot-20260827.zip
# (see bestrom_a17_backup/RESTORE.md), built on a LineageOS base. The stale
# ro.bestrom.version=1.0-a17 that used to sit in the device tree was NOT the
# release version - the real one lived in the old vendor_bestrom/config/version.mk,
# which is unusable on this base. The major bump marks the LineageOS -> VoltageOS
# migration, which is a larger discontinuity than 1.0 -> 2.0 was.
BESTROM_VERSION_MAJOR := 3
BESTROM_VERSION_MINOR := 0
BESTROM_VERSION := $(BESTROM_VERSION_MAJOR).$(BESTROM_VERSION_MINOR)

# Never OFFICIAL unless BestROM actually publishes an official device list.
BESTROM_BUILD_TYPE ?= UNOFFICIAL

# Matches VoltageOS's own scheme (vendor/voltage/config/version.mk) so the two
# build dates in build.prop agree.
BESTROM_BUILD_DATE := $(shell date -u +%Y%m%d-%H%M)

# Set by the device makefile before inheriting this file.
BESTROM_DEVICE ?= $(VOLTAGE_BUILD)

BESTROM_DISPLAY_VERSION := $(BESTROM_VERSION)-$(BESTROM_DEVICE)-$(BESTROM_BUILD_DATE)-$(BESTROM_BUILD_TYPE)
BESTROM_FINGERPRINT := BestROM/$(BESTROM_VERSION)/$(BESTROM_DEVICE)/$(BESTROM_BUILD_DATE)

# /system/build.prop, alongside the platform properties. These were previously
# PRODUCT_PRODUCT_PROPERTIES, which put them in /product/etc/build.prop where
# nothing reads them.
PRODUCT_SYSTEM_DEFAULT_PROPERTIES += \
    ro.bestrom.version=$(BESTROM_DISPLAY_VERSION) \
    ro.bestrom.releasetype=$(BESTROM_BUILD_TYPE) \
    ro.bestrom.build.date=$(BESTROM_BUILD_DATE) \
    ro.bestrom.device=$(BESTROM_DEVICE) \
    ro.bestrom.fingerprint=$(BESTROM_FINGERPRINT) \
    ro.modversion=BestROM-$(BESTROM_DISPLAY_VERSION)

# Build-time resource overlays. Rebrands the setup wizard and repoints the
# updater at BestROM's OTA feed. vendor/voltage/overlay/common touches neither,
# so there is no ordering conflict with vendor/voltage/config/common.mk:193.
PRODUCT_PACKAGE_OVERLAYS += \
    vendor/bestrom/overlay/common

# vendor/voltage/config/packages.mk:23-26 ships Updater only on OFFICIAL
# builds. BestROM is UNOFFICIAL but publishes its own OTA feed, so it is added
# back here. Its privapp whitelist and default-permissions come along via the
# required: block in packages/apps/Updater/app/Android.bp.
PRODUCT_PACKAGES += \
    Updater

# Freezer - BestROM's native app freezer (packages/apps/Freezer, from
# bestrom-peridot-source@packages-apps-freezer). A platform-signed privileged
# system_ext app; its power comes from the platform signature plus the privapp
# allowlist, with no Shizuku or root path.
#
# Its own rom/README.md says to add this by patching vendor/voltage/config/packages.mk.
# We do it here instead: BestROM does not fork vendor/voltage, and that patch's
# context does not match this tree anyway (it anchors on an OpenCamera block that
# this packages.mk does not have).
#
# The privapp allowlist module comes along automatically via the required: clause
# in packages/apps/Freezer/Android.bp - it must not be listed separately. All four
# signature|privileged permissions it requests are allowlisted; a mismatch aborts
# the boot on a build with ro.control_privapp_permissions=enforce.
PRODUCT_PACKAGES += \
    Freezer

# NOTE: org.voltage.version cannot be redefined here. It is what the Settings
# "About" version row displays (VoltageVersionPreference.kt:100) and what the
# Updater reports as PROP_BUILD_VERSION (Constants.java:43), and it would be
# natural to want it to carry the BestROM version. Two things prevent it:
#
#   1. build/soong/scripts/gen_build_prop.py rejects duplicate assignments
#      outright - "error: found duplicate sysprop assignments". The first-wins
#      behaviour in that file is the legacy path, gated behind
#      BUILD_BROKEN_DUP_SYSPROP, and is not active.
#   2. Overriding the VOLTAGEVERSION make variable instead does not work
#      either: vendor/voltage/config/version.mk:16 assigns it with := and is
#      inherited before this file.
#
# So the About row shows the VoltageOS platform version, 6.1. The BestROM
# version is carried by ro.bestrom.version and ro.modversion above. Changing
# the row's value would mean forking vendor/voltage.
#
# The rest of the ro.voltage.* set is deliberately NOT touched. It is plumbing,
# not branding, and stripping it breaks real functionality:
#   ro.voltage.device                       - the Updater substitutes this for
#                                             {device} in the OTA feed URL
#                                             (Utils.java:145,154,160)
#   ro.voltage.platform_release_or_codename - backuptool.sh:51 and
#                                             backuptool_ab.sh:59 grep it to
#                                             guard addon.d restore over an OTA
#   ro.voltage.build.status                 - read by Settings
#                                             VoltageMaintainerPreference and
#                                             HomepageToastManager
