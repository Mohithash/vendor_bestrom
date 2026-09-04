#
# SPDX-FileCopyrightText: BestROM
# SPDX-License-Identifier: Apache-2.0
#
# Auto-included by build/make/core/Makefile:8146, which globs
# vendor/*/build/tasks/*.mk.
#
# This deliberately defines a NEW goal rather than redefining "bacon".
# vendor/voltage/build/tasks/bacon.mk:30 already owns that target; a second
# recipe for it produces "warning: overriding recipe for target 'bacon'" and
# one of the two wins nondeterministically. Build with: mka bestrom

BESTROM_TARGET_PACKAGE := $(PRODUCT_OUT)/BestROM-$(BESTROM_DISPLAY_VERSION).zip

BESTROM_SHA256 := prebuilts/build-tools/path/$(HOST_PREBUILT_TAG)/sha256sum

.PHONY: bestrom
bestrom: $(DEFAULT_GOAL) $(INTERNAL_OTA_PACKAGE_TARGET)
	@# Copy, do not hardlink: the OTA package is rewritten in place each build,
	@# so a hardlinked versioned name silently turns into the NEWEST build.
	@# On 2026-09-04 twelve differently-named zips shared one inode.
	$(hide) cp -f $(INTERNAL_OTA_PACKAGE_TARGET) $(BESTROM_TARGET_PACKAGE)
	$(hide) $(BESTROM_SHA256) $(BESTROM_TARGET_PACKAGE) | sed "s|$(PRODUCT_OUT)/||" > $(BESTROM_TARGET_PACKAGE).sha256sum
	$(hide) { \
		echo ""; \
		echo "===================== BestROM build complete ====================="; \
		echo "  Device   : $(TARGET_DEVICE)"; \
		echo "  Package  : $(BESTROM_TARGET_PACKAGE)"; \
		echo "  SHA256   : `cut -d' ' -f1 $(BESTROM_TARGET_PACKAGE).sha256sum`"; \
		echo "  Size     : `du -sh $(BESTROM_TARGET_PACKAGE) | awk '{print $$1}'`"; \
		echo "  Version  : `grep ro.bestrom.version $(PRODUCT_OUT)/system/build.prop | cut -d'=' -f2-`"; \
		echo "=================================================================="; \
		echo ""; \
	}
