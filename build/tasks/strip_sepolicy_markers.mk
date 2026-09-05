# SPDX-FileCopyrightText: 2026 BestROM
# SPDX-License-Identifier: Apache-2.0
#
# Strip source-path comments from the shipped SELinux text files: the
# ";;* lm..." line markers secilc leaves in .cil files and the "#line ..."
# markers m4 leaves in the *_contexts files. They only carry build-tree paths
# (device/voltage/sepolicy/...) that a ROM detector can grep; secilc and the
# contexts parsers treat ';' / '#' lines as comments, so nothing changes
# functionally.
#
# Safety: the device boots the prebuilt precompiled_sepolicy on /odm. init
# accepts it by comparing two BUILD-TIME hash files with each other
# (/{system,system_ext,product}/etc/selinux/<part>_sepolicy_and_mapping.sha256
# vs precompiled_sepolicy.<part>_sepolicy_and_mapping.sha256 on /odm); it never
# hashes the .cil text at runtime (system/core/init/selinux.cpp,
# FindPrecompiledSplitPolicy). So the .cil content can be edited freely and
# the hash files must be left exactly as the build produced them.

BESTROM_SEPOLICY_STAMP := $(PRODUCT_OUT)/obj/PACKAGING/bestrom_sepolicy_strip.stamp
BESTROM_SEPOLICY_CILS := \
    $(TARGET_OUT_VENDOR)/etc/selinux/vendor_sepolicy.cil \
    $(TARGET_OUT_VENDOR)/etc/selinux/plat_pub_versioned.cil \
    $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/system_ext_sepolicy.cil
BESTROM_SEPOLICY_CONTEXTS := $(wildcard \
    $(TARGET_OUT)/etc/selinux/*contexts \
    $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/*contexts \
    $(TARGET_OUT_PRODUCT)/etc/selinux/*contexts \
    $(TARGET_OUT_VENDOR)/etc/selinux/*contexts \
    $(TARGET_OUT_ODM)/etc/selinux/*contexts)

$(BESTROM_SEPOLICY_STAMP): $(BESTROM_SEPOLICY_CILS) \
        $(TARGET_OUT)/etc/selinux/plat_property_contexts \
        $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/system_ext_property_contexts \
        $(TARGET_OUT_PRODUCT)/etc/selinux/product_property_contexts \
        $(TARGET_OUT_VENDOR)/etc/selinux/vendor_property_contexts \
        $(TARGET_OUT_ODM)/etc/selinux/odm_property_contexts
	@echo "BestROM: stripping SELinux source-path comments"
	$(hide) for f in $(BESTROM_SEPOLICY_CILS); do [ -f $$f ] && sed -i '/^;;\* lm/d' $$f; done; true
	$(hide) for f in $(TARGET_OUT)/etc/selinux/*contexts $(TARGET_OUT_SYSTEM_EXT)/etc/selinux/*contexts \
	              $(TARGET_OUT_PRODUCT)/etc/selinux/*contexts $(TARGET_OUT_VENDOR)/etc/selinux/*contexts \
	              $(TARGET_OUT_ODM)/etc/selinux/*contexts; do [ -f $$f ] && sed -i '/^#line /d' $$f; done; true
	$(hide) mkdir -p $(dir $@) && touch $@

$(INSTALLED_SYSTEMIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_SYSTEM_EXTIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_PRODUCTIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_VENDORIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
$(INSTALLED_ODMIMAGE_TARGET): $(BESTROM_SEPOLICY_STAMP)
