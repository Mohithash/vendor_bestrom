# SPDX-FileCopyrightText: 2026 BestROM
# SPDX-License-Identifier: Apache-2.0
#
# Strip source line-marker comments (";;* lm...") from the shipped SELinux
# .cil files. These are debug-only comments that embed build-tree paths such
# as device/voltage/sepolicy, which a ROM detector can grep for. secilc
# ignores ";" comments, so removing them changes nothing functionally.
#
# The compiled policy the device actually loads is the prebuilt
# precompiled_sepolicy on /odm; the *_sepolicy.cil files are only recompiled
# on-device if the precompiled binary is rejected. init decides that by
# hashing each partition's <part>_sepolicy.cil + its mapping/<ver>.cil and
# comparing to precompiled_sepolicy.<part>_sepolicy_and_mapping.sha256. Only
# system_ext_sepolicy.cil carries markers among the hashed cils, so after
# stripping it we regenerate that one sha256 so the gate still matches and no
# boot-time recompile is triggered. vendor_sepolicy.cil is not hashed.

BESTROM_SEPOLICY_MAP_VER := 202604
BESTROM_SEPOLICY_STAMP := $(PRODUCT_OUT)/obj/PACKAGING/bestrom_sepolicy_strip.stamp
BESTROM_VENDOR_CIL := $(TARGET_OUT_VENDOR)/etc/selinux/vendor_sepolicy.cil
BESTROM_SYSEXT_CIL := $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/system_ext_sepolicy.cil
BESTROM_SYSEXT_MAP := $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/mapping/$(BESTROM_SEPOLICY_MAP_VER).cil
BESTROM_SYSEXT_SHA := $(TARGET_OUT_ODM)/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256

$(BESTROM_SEPOLICY_STAMP): $(BESTROM_VENDOR_CIL) $(BESTROM_SYSEXT_CIL) $(BESTROM_SYSEXT_MAP) $(BESTROM_SYSEXT_SHA)
	@echo "BestROM: stripping SELinux line-marker comments"
	$(hide) sed -i '/^;;\* lm/d' $(BESTROM_VENDOR_CIL)
	$(hide) sed -i '/^;;\* lm/d' $(BESTROM_SYSEXT_CIL)
	$(hide) cat $(BESTROM_SYSEXT_CIL) $(BESTROM_SYSEXT_MAP) | sha256sum | cut -d' ' -f1 | tr -d '\n' > $(BESTROM_SYSEXT_SHA)
	$(hide) mkdir -p $(dir $@) && touch $@

$(INSTALLED_VENDORIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_SYSTEM_EXTIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_ODMIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
