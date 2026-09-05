# SPDX-FileCopyrightText: 2026 BestROM
# SPDX-License-Identifier: Apache-2.0
#
# BestROM boot animation. A device points BESTROM_BOOTANIMATION at its
# canonical zip (see device/xiaomi/peridot/device.mk); after the product
# image install step that file is copied over VoltageOS's
# product/media/bootanimation.zip. A Soong prebuilt at the same install
# path would lose the collision, hence the post-install copy.

ifneq ($(strip $(BESTROM_BOOTANIMATION)),)
BESTROM_BOOTANIMATION_INSTALLED := $(TARGET_OUT_PRODUCT)/media/bootanimation.zip
BESTROM_BOOTANIMATION_STAMP := $(PRODUCT_OUT)/obj/PACKAGING/bestrom_bootanimation.stamp

$(BESTROM_BOOTANIMATION_STAMP): $(BESTROM_BOOTANIMATION) $(BESTROM_BOOTANIMATION_INSTALLED)
	@echo "BestROM: installing boot animation over product/media/bootanimation.zip"
	$(hide) cp -f $(BESTROM_BOOTANIMATION) $(BESTROM_BOOTANIMATION_INSTALLED)
	$(hide) mkdir -p $(dir $@) && touch $@

$(INSTALLED_PRODUCTIMAGE_TARGET): $(BESTROM_BOOTANIMATION_STAMP)
endif
