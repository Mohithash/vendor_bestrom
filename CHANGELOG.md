BestROM 3.0 for POCO F6 (peridot)
=================================

Release:   3.0-peridot-20260905-1529-UNOFFICIAL
Package:   BestROM-3.0-peridot-20260905-1530-UNOFFICIAL.zip (2763830995 bytes)
sha256:    37e5b7b3e6c2144ec3ff443b8a8d6289d6ec31888e1a73d9ed934ea88dae9e59
Android:   17 (SDK 37), AOSP android-17.0.0_r1, VoltageOS 6.1 base
Kernel:    6.1.176 GKI (android14-6.1), Theettam 2.7 lts176
Patch:     platform 2026-08-01, vendor 2026-06-01 (OS3.0.302.0.WNPMIXM blobs)
Previous:  2026-08-27 (BestROM A17)

Flashing
--------
Boot to recovery, then:

    adb sideload BestROM-3.0-peridot-20260905-1530-UNOFFICIAL.zip

The package flashes boot and vendor_boot together; do not mix the kernel
from one build with the modules of another (vermagic must match). Dirty
flash over the 2026-08-27 build is supported. No wipe required.


Changes since 2026-08-27
------------------------

Kernel
  net: qrtr: raise QRTR_NS_MAX_LOOKUPS to 512. The 6.1.176 cap of 64
      starved the sensors HAL on the sm8635 vendor stack; system_server
      hit its watchdog and the device boot-looped.
  ci: stop forcing KSU_SUSFS_ENABLE_LOG into every SUSFS flavor.

HALs
  power: ship android.hardware.power-service (libperfmgr). Was missing
      from the image because of a typo in the package name.
  thermal: ship android.hardware.thermal-service.qti. Was missing.
  touch: vendor.lineage.touch -> vendor.bestrom.touch (AIDL v1 frozen,
      hash regenerated), implementation and VINTF updated.
  ir, power: binaries renamed from *.lineage to *.xiaomi; power HAL log
      tag follows.
  seccomp: allow lseek for atfwd and qesdk-secmanager. minijail killed
      both every 5 s.
  seccomp: drop _llseek and the duplicate getdents64 line from the
      codec2 and c2audio ext-arm64 policies. _llseek is a 32-bit
      syscall name; minijail on arm64 rejected the whole policy.
  servicemanager: hide bestrom* / vendor.bestrom.* services from
      untrusted apps, same filter as the lineage names.

SELinux
  Rename the Lineage SDK type identifiers to bestrom_* (hal_lineage_*,
      lineage_*_service). adbroot domain -> bestrom_adbctl; rules kept.
  Rename HAL binary and service names in file_contexts and
      service_contexts; drop the unshipped lineage.hardware.radio
      hwservice contexts.
  Strip secilc ";;* lm" and m4 "#line" source-path comments from the
      shipped .cil and *_contexts files. The precompiled policy and its
      hash gate files are not touched.
  peridot: label vendor.qti.qspmhal@1.0.so same_process_hal_file;
      allow platform apps to find and call IBGService (MiuiCamera);
      label the camera provider's IVirtualCameraRegistrar; make the
      mi_thermald property context a vendor.sys.thermal. prefix.
  Label /data/bestrom_updates and the com.bestrom.updater seapp entry.

System properties
  Retire ro.voltage.*, org.voltage.version and ro.modversion. The
      surviving values move to ro.bestrom.* (build.status,
      platform_release_or_codename, maintainer.gpg_key/uid) and
      org.bestrom.version. Readers updated: Settings, Updater, recovery,
      backuptool, releasetools, DisplayResolutionManager, bootanimation.
  ro.system.build.fingerprint now carries the same stock POCO value as
      the other fingerprints. It leaked the real android-17 build id and
      the "eng.<user>" build number.
  BUILD_NUMBER is set explicitly at build time.
  dalvik: 12 GB heap tier (heapgrowthlimit 384m; the 6 GB tier gave 256m).

Framework
  Known setup-wizard package is org.bestrom.setupwizard.
  Boot-jar package check allows vendor.bestrom.*.
  LatinIME is dexpreopted with the speed filter, like SystemUI and the
      launcher.

Apps
  SetupWizard: package org.lineageos.setupwizard -> org.bestrom.setupwizard,
      module VoltageSetupWizard -> BestromSetupWizard. BestROM mark.
  Updater: package com.voltage.updater -> com.bestrom.updater; download
      directory /data/bestrom_updates; reads ro.bestrom.device and
      org.bestrom.version.
  FaceUnlock: package com.voltageos.faceunlock -> com.bestrom.faceunlock.
      The framework binds by action, not package.
  Freezer: launcher icon; in-place empty state instead of a toast that
      died with the activity; confirm dialog for the add-apps picker;
      unused-app scan runs only in Doze maintenance windows.
  Settings: BestROM strings and labels; Android version page shows the
      dotted-B vector with no background (was a JPEG with a black square);
      reads ro.bestrom.*.
  Font overlays: org.voltage.theme.font.* -> org.bestrom.theme.font.*.
  MiuiCamera replaces Aperture. VoltageJump removed.

Theme and UI
  FrameworkOverlayPeridot no longer overrides
      background_device_default_light to #000000. Toasts, popups and the
      Settings bottom bar rendered black-on-black in the light theme. The
      dark override is kept.
  Boot animation: the device tree's canonical 1440x2560 animation is
      shipped again; the generated one is dropped.
  Recovery: dot-matrix RECOVERY / FASTBOOTD header, monochrome grey
      scheme in both modes, install spinner taken from the boot
      animation, dot-matrix error icon, title from ro.bestrom.version.
  Default wallpaper is pure black.


Known issues
------------
  Bootloader is unlocked and AVB is disabled; hardware attestation
      reports it. Play Integrity DEVICE and STRONG fail. Unchanged.
  Dolby codec2 blob (from pdx245): E-AC3 / AC-4 playback not verified;
      a mediacodeclist_generator tombstone at boot has been observed.
  init.qti.media.rc, xiaomi_modem_sh, xiaomi_modem_cust_sh reference
      scripts that are not in the image. No effect observed.
  LineageOS SDK namespace (org.lineageos.platform, lineage* binder
      service names) is unchanged.
  Glimpse, QtiTelephonyCompat, GmsCompat, CalyxOS and ProtonAOSP
      components keep their upstream package ids.
