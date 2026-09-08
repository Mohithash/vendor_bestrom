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
# Official BestROM builds come from the maintainer's environment (BESTROM_OFFICIAL=true),
# the same switch vendor/voltage/config/version.mk honours.
ifeq ($(BESTROM_OFFICIAL),true)
BESTROM_BUILD_TYPE := OFFICIAL
else
BESTROM_BUILD_TYPE := UNOFFICIAL
endif

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
    org.bestrom.version=$(BESTROM_VERSION)

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

# BestromPreinstaller (packages/apps/BestromPreinstaller) - installs
# vendor-bundled third-party APKs as normal, fully removable user apps on
# first boot, via PackageInstaller. This is what lets BestROM ship optional
# third-party apps without them being permanent, unremovable system apps.
#
# NOT added to a separate vendor/bestrom/config/packages.mk: this file
# (branding.mk) is the only vendor/bestrom/config/*.mk that
# device/xiaomi/peridot/bestrom_peridot.mk actually inherits (see its
# `$(call inherit-product, vendor/bestrom/config/branding.mk)` at line 40,
# with no matching call for any packages.mk). A packages.mk would need its
# own inherit-product line added to the device makefile to not be dead
# weight - exactly the kind of silent no-op already documented above for the
# old PRODUCT_PACKAGES filter-out line. Simplest correct fix is to add the
# package here, alongside Updater and Freezer, where it is known to be
# inherited.
#
# The privapp allowlist module comes along automatically via the required:
# clause in packages/apps/BestromPreinstaller/Android.bp.
PRODUCT_PACKAGES += \
    BestromPreinstaller

# Edge - gesture and key remapping (packages/apps/Edge), a native port of the
# EdgeX Xposed module. A platform-signed privileged system_ext app; instead of
# Xposed it is loaded into system_server by com.android.server.bestrom.EdgeLoader
# at the end of InputManagerService.start(), and InputManagerService calls it on
# the input filter and key interception paths.
#
# The privapp allowlist module comes along automatically via the required:
# clause in packages/apps/Edge/Android.bp.
PRODUCT_PACKAGES += \
    Edge

# BestromAgent (packages/apps/BestromAgent) - the Agent mode bridge. A
# platform-signed privileged system_ext app whose every component ships
# android:enabled="false": with the switch off it is an APK on disk and
# nothing else. No receiver, no job, no provider, no notification listener,
# so it is not in the boot path and not in the idle drain budget.
#
# Its privapp allowlist (EXECUTE_APP_FUNCTIONS, WRITE_SECURE_SETTINGS) comes
# along automatically via the required: clause in
# packages/apps/BestromAgent/Android.bp - it must not be listed separately. A
# mismatch between that file and the app manifest aborts the boot on a build
# with ro.control_privapp_permissions=enforce.
PRODUCT_PACKAGES += \
    BestromAgent

# NOTE: org.bestrom.version is assigned above and only above. It is what the
# Updater reports as PROP_BUILD_VERSION (Constants.java) and what the Settings
# "About" version row reads, so it carries the short BESTROM_VERSION - the same
# value the OTA feed advertises for an offered build - instead of VoltageOS's
# platform version.
#
# vendor/voltage is a BestROM fork (Mohithash/vendor_voltage, branch
# bestrom-a17), so the old assignment in its config/version.mk was removed
# rather than worked around. That leaves exactly one assignment, which is what
# build/soong/scripts/gen_build_prop.py's duplicate-sysprop check requires;
# overriding the VOLTAGEVERSION make variable from here never worked, because
# version.mk assigns it with := and is inherited first.
#
# No ro.voltage.* property name exists any more. The equivalent set is
# ro.bestrom.*, split over two files: this one defines
# ro.bestrom.{version,releasetype,build.date,device,fingerprint}, and
# vendor/voltage/config/version.mk defines ro.bestrom.build.status,
# ro.bestrom.platform_release_or_codename and the maintainer GPG pair. Those
# are plumbing, not branding, and stripping them breaks real functionality:
#   ro.bestrom.device                       - the Updater substitutes this for
#                                             {device} in the OTA feed URL
#                                             (Utils.java:145,154,160)
#   ro.bestrom.platform_release_or_codename - backuptool.sh:51 and
#                                             backuptool_ab.sh:59 grep it to
#                                             guard addon.d restore over an OTA
#   ro.bestrom.build.status                 - read by Settings
#                                             VoltageMaintainerPreference and
#                                             HomepageToastManager

# Cromite's SystemWebView build in place of the AOSP prebuilt. The module's
# overrides: ["webview"] drops the one build/make/target/product/media_product.mk
# adds, so external/chromium-webview stays in the tree but installs nothing.
#
# No config_webview_packages.xml overlay: Cromite keeps the AOSP package name
# com.android.webview, and vendor/voltage/overlay/common already overlays that
# file with an entry for it (description "AOSP WebView", availableByDefault,
# isFallback, no <signature>). A BestROM copy could not win anyway - the aapt2
# overlay order is the PRODUCT_PACKAGE_OVERLAYS order and the first root wins,
# and a product makefile's own additions always flatten after the ones it
# inherits, so vendor/bestrom/overlay/common cannot outrank
# vendor/voltage/overlay/common for a file both of them carry.
#
# The APK is not in git - it is 297 MB, which GitHub will not take and which
# Git LFS would only turn into a monthly bandwidth quota that every clone
# spends. tools/fetch-prebuilts.sh downloads it and checks its digest against
# GitHub's release attestation. Fail here rather than several minutes into
# Soong on an "apk: missing dependency" that says nothing about the cause.
$(if $(wildcard vendor/bestrom/prebuilt/CromiteWebView/CromiteWebView.apk),,\
    $(error CromiteWebView.apk missing: run vendor/bestrom/tools/fetch-prebuilts.sh))

PRODUCT_PACKAGES += \
    CromiteWebView

# LeanType in place of AOSP LatinIME. LatinIME is added twice - by
# build/make/target/product/handheld_product.mk and by
# vendor/voltage/config/common_mobile.mk - so it cannot be dropped from here;
# the module's overrides: ["LatinIME"] removes both.
#
# LeanType publishes no locale-tagged subtypes, so the framework will not
# auto-enable it once LatinIME is gone. BestromPreinstaller seeds
# Settings.Secure.DEFAULT_INPUT_METHOD on first boot; see
# vendor/bestrom/prebuilt/LeanType/README.md.
PRODUCT_PACKAGES += \
    LeanType

# The keyboard is deliberately NOT in PRODUCT_DEXPREOPT_SPEED_APPS, where
# LatinIME used to be: on peridot that list changes nothing, because
# device/xiaomi/peridot/device.mk sets
# PRODUCT_DEX_PREOPT_DEFAULT_COMPILER_FILTER := speed and every app is AOT
# compiled whole regardless. Better to not claim an intent the entry does not
# carry.
#
# The size is real either way, and it is the largest line item in this swap.
# LatinIME's bulk was dictionary assets and it compiled to a 2.3 MB odex;
# LeanType's bulk is code. Measured on the module's own output: a 24,548,742 B
# APK (Soong uncompresses classes*.dex for dexpreopt), a 32,513,752 B odex and
# a 485,168 B vdex - 57,547,662 B installed, about +35 MB against LatinIME's
# 22 MB. Recovering it means changing the device-wide compiler filter, which is
# every app's decision, not this one's.

# Removable preloads: installed once on first boot by BestromPreinstaller as
# ordinary user apps, so users can uninstall them. Via Browser 7.3.3
# (mark.via.gp, https://viayoo.com, sha256 245e02eb1106dfd4d97d27f5bb68e97a2db9fe543f72ab93dc6b587b0e2da4fd).
# MiXplorer 6.71.15 (com.mixplorer, https://mixplorer.com, arm64 split, sha256
# bc2627659872cfc9895155d129c03eb8ac2b3c112cbdbe7303feb718f10c83f0). Copied
# verbatim and never re-signed: the author permits ROMs to preinstall MiXplorer
# but not to ship a modified or differently signed APK. See
# vendor/bestrom/prebuilt/preinstall/README.md.
#
# RELEASE SIGNING. Every release-signing run over a target-files zip carrying
# these two APKs must be given
#
#     --skip_apks_with_path_prefix PRODUCT/etc/bestrom/preinstall/
#
# and it is not optional. sign_target_files_apks decides what is an APK by file
# extension anywhere in the zip (GetApkFileInfo), but META/apkcerts.txt is
# generated only from $(PACKAGES) - module names - so a PRODUCT_COPY_FILES entry
# never gets a line in it and the run dies on
# "No key specified for: MiXplorer.apk, Via.apk". The skip prefix drops both out
# of that check and copies them into the signed target-files byte for byte,
# which is what MiXplorer's terms require anyway. Do NOT answer the assertion by
# adding them to apkcerts with the release key: that re-signs MiXplorer with a
# different signature, exactly what the author forbids. -e MiXplorer.apk= -e
# Via.apk= (empty value, meaning do not sign) works too, but the prefix keeps
# covering the next APK dropped in this directory.
PRODUCT_COPY_FILES += \
    vendor/bestrom/prebuilt/preinstall/Via.apk:$(TARGET_COPY_OUT_PRODUCT)/etc/bestrom/preinstall/Via.apk \
    vendor/bestrom/prebuilt/preinstall/MiXplorer.apk:$(TARGET_COPY_OUT_PRODUCT)/etc/bestrom/preinstall/MiXplorer.apk

# Typography. Two OFL-1.1 variable faces from google/fonts, installed to
# /product/fonts by prebuilt_font modules in vendor/bestrom/prebuilt/fonts.
# The families themselves are declared in vendor/voltage/fonts/fonts_customization.xml
# - /product/etc/fonts_customization.xml is the ONLY OEM font hook the platform
# reads (SystemFonts.java OEM_XML, system_fonts.cpp), there can be exactly one of
# it, and vendor/voltage already owns the module that installs it, so a family is
# added by editing that file rather than by shipping a second one.
# frameworks/base/data/fonts/fonts.xml is NOT edited - it is deprecated as a source
# of installed fonts on A17 and nothing would pick the entry up.
PRODUCT_PACKAGES += \
    Doto-Variable.ttf \
    SpaceGrotesk-Variable.ttf

# The families are selected by config_bodyFontFamily / config_headlineFontFamily /
# config_clockFontFamily in device/xiaomi/peridot/overlay/FrameworkOverlayPeridot.
# No font RRO and no /product/overlay/config/config.xml: shipping an overlay config
# for a partition turns OFF the android:isStatic -> immutable, default-enabled
# conversion for every other overlay on that partition (OverlayConfig skips the
# fallback as soon as getConfigurations() returns non-null), which would silently
# disable the carrier, telephony, network-stack, permission-controller, DocumentsUI
# and face-unlock overlays that live on /product.
