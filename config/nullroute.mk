# Nullroute — product wiring.
#
# Placed from packages/apps/Nullroute/rom/nullroute.mk. It is reached by exactly
# ONE line at the end of vendor/bestrom/config/branding.mk:
#
#     include vendor/bestrom/config/nullroute.mk
#
# NOT vendor/voltage/config/common.mk, which is what the upstream README says.
# device/xiaomi/peridot/bestrom_peridot.mk inherits exactly one file out of
# vendor/bestrom/config, and that file is branding.mk; a second .mk placed
# beside it is dead weight until something inherits it. Keeping the line in
# branding.mk also keeps BestROM's product additions out of vendor/voltage, so
# the Voltage rebase surface stays clean.
#
# One include line means one merge conflict per rebase instead of N.
# system/core/rootdir/etc/hosts is never edited in place — we override the
# module instead — so a rebase never conflicts there either.

# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------
#
# The app's `required:` list in packages/apps/Nullroute/Android.bp pulls in the
# permission XMLs, the sysconfig XMLs, init.nullroute.rc, the baked list data
# and the QS tile overlay, so they are deliberately not repeated here. Only the
# four top-level artefacts are named.

# ⚠ THE APP IS NOT IN THIS LIST YET, AND THAT IS NOT AN OVERSIGHT.
#
# packages/apps/Nullroute is missing the whole com.bestrom.nullroute.build
# package - IndexBuilder, CanarySet and NeverBlockFloor. Eight Kotlin files
# import it (core/Generation.kt, importer/ImportModel.kt, job/UpdateJobService.kt,
# ui/UpdateFragment.kt, ui/RecoveryActions.kt and three more) and there is no
# such directory in the repository, so `mka Nullroute` fails at the Kotlin
# compile with ~40 unresolved references. Nothing in this tree can fix that; the
# source has to arrive upstream.
#
# What ships meanwhile is exactly the de-risking set rom/README.md section 11
# asks for on day one: the L0 hosts floor, the four resolver hooks, the SELinux
# policy, init.nullroute.rc, the seeder and the CLI. The resolver falls open with
# no index, which is the designed behaviour, so the device is coherent - it
# simply blocks only what L0 carries.
#
# TO TURN THE APP BACK ON once the build package lands: uncomment Nullroute
# below and delete the explicit block after it. Those modules are only listed
# because the app's `required:` clause in packages/apps/Nullroute/Android.bp is
# what normally pulls them in, and with the app absent nothing else names them.
PRODUCT_PACKAGES += \
    nrctl \
    nullroute_seed \
    nullroute_etc_hosts

# PRODUCT_PACKAGES += \
#     Nullroute

# Stand-ins for the app's `required:` list. Deliberately NOT the five
# app-scoped XMLs (privapp_whitelist_com.bestrom.nullroute,
# nullroute_gid_permissions, preinstalled-packages-platform-nullroute,
# sysconfig-nullroute, default-permissions-nullroute): every one of them is
# configuration for a package that is not installed, and shipping permission
# grants for an absent app is the kind of thing that outlives the reason for it.
# They come back automatically with the app, through `required:`.
PRODUCT_PACKAGES += \
    init.nullroute.rc \
    nullroute_baseline_domains \
    nullroute_baseline_domains_sha256 \
    nullroute_neverblock \
    nullroute_antifraud \
    nullroute_attribution \
    nullroute_profile_lite \
    nullroute_profile_balanced \
    nullroute_profile_aggressive

# ---------------------------------------------------------------------------
# Guard 1 — anti-substitution (F11)
# ---------------------------------------------------------------------------
#
# THE PROBLEM THIS SOLVES IS THAT SUCCESS AND FAILURE LOOK IDENTICAL.
#
# In this tree libnetd_resolv lives in packages/modules/DnsResolver and ships
# inside the com.android.tethering APEX (verified: apex_available lists
# com.android.tethering, min_sdk_version apex_inherit). If a prebuilt Google
# mainline APEX is installed over the source-built one, the block hook is simply
# not in the binary that runs — and the app, the UI, the index, the sepolicy and
# the canary all keep working flawlessly while blocking nothing. There is no
# runtime signal and no error anywhere in the build.
#
# So the guard scans BOTH lists, and it scans for the *tethering* APEX as well
# as any resolv APEX, because in this tree tethering is the one that matters.
#
# ⚠ SCOPE, AND IT IS NARROWER IN THIS TREE THAN THE GUARD ASSUMES. branding.mk
# is reached through $(call inherit-product ...), and inherit-product DEFERS its
# nodes: at the moment this file is read, PRODUCT_PACKAGES holds inherit markers,
# not package names, so the filters below match nothing. The same trap is
# documented with shipped-build proof in device/xiaomi/peridot/bestrom_peridot.mk
# (a PRODUCT_PACKAGES filter-out there never removed anything). The guard is kept
# because it costs nothing and would fire on a direct include, but DO NOT treat a
# clean build as evidence that it ran. The real anti-substitution control here is
# tools/ci_verify_image.sh, which re-asserts the same thing against the finished
# image, where nothing can hide. Run it every time.

# com.android.resolv and com.android.tethering are the SOURCE-BUILT AOSP module
# names and are legitimate; everything else matching is a prebuilt.
_nr_ok_apex := com.android.resolv com.android.tethering

# The patterns are anchored on `com.` so that ordinary modules whose names happen
# to end in one of these words — libnetd_resolv is the obvious one — cannot trip
# a $(error) that would look like a real substitution. Every prebuilt mainline
# APEX is named com.<vendor>.android.<module>, so nothing real is missed.
_nr_bad_pkgs := \
    $(filter-out $(_nr_ok_apex), \
        $(filter com.%resolv com.%resolv.apex com.%resolv.capex \
                 com.%tethering com.%tethering.apex com.%tethering.capex, \
            $(PRODUCT_PACKAGES)))

# PRODUCT_COPY_FILES entries are src:dest[:...]. Check every colon-separated
# word, because a prebuilt can arrive as either half:
#   prebuilts/.../com.google.android.tethering.apex:system/apex/com.google.android.tethering.apex
_nr_copy_words := $(foreach p,$(PRODUCT_COPY_FILES),$(subst :, ,$(p)))
# No filter-out of the AOSP names here, unlike PRODUCT_PACKAGES above: the
# source-built APEX is always placed by PRODUCT_PACKAGES, never copied. Any
# .apex/.capex arriving through PRODUCT_COPY_FILES is by definition a prebuilt,
# including one that has been renamed to the AOSP module name.
_nr_bad_copy := \
    $(filter %resolv.apex %resolv.capex %tethering.apex %tethering.capex, \
        $(notdir $(_nr_copy_words)))

ifneq ($(strip $(_nr_bad_pkgs)$(_nr_bad_copy)),)
  $(warning Nullroute: PRODUCT_PACKAGES offenders: $(_nr_bad_pkgs))
  $(warning Nullroute: PRODUCT_COPY_FILES offenders: $(_nr_bad_copy))
  $(error Nullroute: a prebuilt mainline APEX would replace the source-built \
          resolver. libnetd_resolv ships inside com.android.tethering in this \
          tree, so a prebuilt tethering OR resolv APEX silently deletes the \
          block hook while leaving every other part of the feature working. \
          Remove it, or drop Nullroute from the product)
endif

_nr_ok_apex :=
_nr_bad_pkgs :=
_nr_copy_words :=
_nr_bad_copy :=

# ---------------------------------------------------------------------------
# Guard 2 — Tiny UDP Cannon
# ---------------------------------------------------------------------------
#
# Any app holding only the auto-granted INTERNET permission can make
# system_server transmit attacker-chosen bytes on the original network,
# bypassing VPN lockdown, via the tethering module's QUIC connection-close
# payload. Google marked it Won't Fix; GrapheneOS disabled it in 2026050400.
#
# This ships regardless of which Nullroute layer is enabled — it is not our bug
# and it is not conditional on our feature. -1 disables the payload.
#
# The app additionally calls
#   DeviceConfig.setProperty("tethering", "close_quic_connection", "-1", false)
# at boot from job/DeviceConfigFixups.kt, because the build.prop form of a
# device_config override is not honoured on every branch.
PRODUCT_PRODUCT_PROPERTIES += \
    persist.device_config.tethering.close_quic_connection=-1

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
#
# The runtime master switch, read by NrFilter before it touches anything else.
# Setting it false in a local build turns the whole feature off without
# rebuilding the resolver — useful for A/B-ing a bug report against the same
# image. It falls through to default_prop on purpose (see the note in
# rom/sepolicy/property_contexts.frag).
#
# The COMPILE-TIME removal is a different lever: -DNULLROUTE_ENABLED in
# packages/modules/DnsResolver/Android.bp. Dropping that define removes the four
# hooks from the binary entirely, which is what you want when bisecting a netd
# crash rather than a filtering bug.
PRODUCT_SYSTEM_EXT_PROPERTIES += \
    ro.nullroute.enabled=true

# ---------------------------------------------------------------------------
# L0 hosts override — fallback path
# ---------------------------------------------------------------------------
#
# nullroute_etc_hosts declares `overrides: ["etc_hosts"]` against the stock
# module in system/core/rootdir/Android.bp. _PATH_HOSTS is the hardcoded literal
# "/system/etc/hosts" (bionic/libc/include/netdb.h:73), so the file has to land
# on /system even though everything else we ship is system_ext — which means the
# override crosses a module boundary that is worth proving rather than assuming.
#
# Spike 6 (SPEC.md §10.6):
#     mka nullroute_etc_hosts && wc -l out/target/product/peridot/system/etc/hosts
# The stock file is 5 lines in THIS tree, not the 2 the upstream README assumes:
# VoltageOS adds three 127.0.0.1 ota*.googlezip.net sinkholes on top of the two
# AOSP entries. Assert >= 2000 rather than "not 2". Note that our prebuilt/hosts
# does not carry those three googlezip lines, so overriding the module drops
# them; that is a deliberate, known behaviour change.
#
# If the override does not win, uncomment the block below — branding.mk is
# inherited after vendor/voltage/config/common_mobile.mk, so a PRODUCT_COPY_FILES
# entry here wins — and drop nullroute_etc_hosts from PRODUCT_PACKAGES above so
# the two mechanisms cannot fight. Dropping it also drops its
# overrides: ["etc_hosts"], and build/make/target/product/base_system.mk adds
# etc_hosts unconditionally, so etc_hosts must then also be listed in the
# RemovePackagesPeridot overrides: block in device/xiaomi/peridot/debloat/Android.bp
# or two rules will generate /system/etc/hosts and ninja will refuse.
#
# PRODUCT_COPY_FILES += \
#     packages/apps/Nullroute/prebuilt/hosts:$(TARGET_COPY_OUT_SYSTEM)/etc/hosts

# ---------------------------------------------------------------------------
# Also required, and NOT expressible here
# ---------------------------------------------------------------------------
#
#   * The addon.d survival list. Upstream says to delete the `etc/hosts` entry
#     from vendor/lineage/prebuilt/common/bin/50-lineage.sh, or the first OTA
#     restores the pre-OTA hosts file over the freshly built one. The equivalent
#     file here is vendor/voltage/prebuilt/common/bin/50-voltage.sh and the entry
#     has been removed from it. The OTA regression could not actually occur on
#     BestROM today — nothing in the tree installs that script and the image has
#     no /system/addon.d at all — so this is defence in depth against Voltage
#     wiring addon.d up later.
#
#   * The com.android.tethering APEX payload and APK-v3 signing keys must be on
#     the BestROM release-key checklist next to the platform key. Getting them
#     wrong bootloops apexd with "public key doesn't match the pre-installed
#     one" — a device-won't-boot problem, not a debugging problem.
#
#     For BestROM specifically the bootloop is not the live risk: the APEX is
#     built from source, its payload key is the in-tree one in
#     packages/modules/Connectivity/Tethering/apex, and the container cert
#     override in vendor/voltage-priv/keys/keys.mk matches the preinstalled one,
#     so a clean flash is self-consistent. The live risk is that those keys are
#     public. Anyone holding them can sign a tethering APEX update that apexd
#     accepts into /data/apex, replacing the patched resolver with an unpatched
#     one — silently, which is this project's worst failure class.
