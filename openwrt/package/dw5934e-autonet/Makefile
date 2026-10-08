include $(TOPDIR)/rules.mk

PKG_NAME:=dw5934e-autonet
PKG_VERSION:=20260830
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_MAINTAINER:=Local delivery

include $(INCLUDE_DIR)/package.mk

define Package/dw5934e-autonet
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=Safe DW5934e (105b:e11d/e11e) MHI/MBIM AutoNet orchestration
  DEPENDS:=+kmod-mhi-bus +kmod-mhi-pci-generic +kmod-wwan +kmod-mhi-wwan-ctrl +kmod-mhi-wwan-mbim +modemmanager +libmbim +mbim-utils +libqmi +qmi-utils
endef

define Package/dw5934e-autonet/description
 Wait for the DW5934e 105b:e11d PCIe/MHI endpoint and configure one
 ModemManager/netifd cellular interface. Kernel modules remain external,
 ABI-matched OpenWrt dependencies; this package contains no kernel binary.
endef

define Package/dw5934e-autonet/conffiles
/etc/config/dw5934e-autonet
endef

define Build/Compile
endef

define Package/dw5934e-autonet/install
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) ./files/etc/config/dw5934e-autonet $(1)/etc/config/dw5934e-autonet
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) ./files/etc/init.d/dw5934e-autonet $(1)/etc/init.d/dw5934e-autonet
	$(INSTALL_DIR) $(1)/usr/sbin
	$(INSTALL_BIN) ./files/usr/sbin/dw5934e-autonet $(1)/usr/sbin/dw5934e-autonet
	$(INSTALL_BIN) ./files/usr/sbin/dw5934e-autonet-status $(1)/usr/sbin/dw5934e-autonet-status
endef

define Package/dw5934e-autonet/postinst
#!/bin/sh
[ -n "$${IPKG_INSTROOT}" ] && exit 0
grep -q 'dw5934e-autonet: skip wireless interfaces' /etc/hotplug.d/net/25-modemmanager-net 2>/dev/null || exit 1
/etc/init.d/modemmanager enable || exit 1
/etc/init.d/modemmanager start || exit 1
/etc/init.d/dw5934e-autonet enable || exit 1
/etc/init.d/dw5934e-autonet start || exit 1
exit 0
endef

$(eval $(call BuildPackage,dw5934e-autonet))
