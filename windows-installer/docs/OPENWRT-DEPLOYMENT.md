# OpenWrt 部署：DW5934e / X72 的保守网络接入指南

本文件只说明 OpenWrt 上的识别、驱动绑定、拨号和排错。先在目标路由器上确认实际枚举和实际内核绑定，再安装包或写入 UCI；不要把 Windows 驱动或 Ubuntu 的厂商 `.ko` 用于 OpenWrt。

## 支持边界

* 已知 USB 形态可见 `05c6:90d5`。只有其 MBIM 接口描述符实际符合 CDC-NCM/MBIM 类、并且内核实际绑定 `cdc_mbim` 时，才可按本文件的 USB MBIM 路径部署。VID/PID 自身不是保证。
* `PCI 105b:e11d` 是 MHI 形态。当前上游 Linux master 的 `pci_generic.c` 已包含 DW5934e sdx72 with eSIM 的 `105b:e11d` 项。
* 当前上游同样包含 Foxconn T99W640 sdx72 的 `105b:e118` 项。两个 ID 由 Linux 6.11 周期的提交 `bf30a75e6e0001c3d473f2bf46d026eb0c4a0bd2` 引入；后续提交修正了 E118 型号名称。
* 这不等于任意 OpenWrt 镜像开箱即用：旧 OpenWrt release、旧内核、厂商树或未回移的构建可能没有这些项。必须检查**目标镜像实际构建的** `pci_generic.c`/提交和实际 dmesg 绑定；只有目标源码缺失时才评估最小回移补丁并自行构建测试。不要仅凭包安装成功就认为网卡可用。

先收集非破坏性事实：

```sh
lsusb
lsmod | grep -E 'mbim|qmi|mhi|wwan'
dmesg | tail -n 120
logread | tail -n 120
ls -l /dev/cdc-wdm* /dev/wwan* 2>/dev/null
```

## USB：优先 MBIM

联网后，安装与当前发行版、target/subtarget、架构和内核 ABI 匹配的包：

```sh
opkg update
opkg install kmod-usb-net-cdc-mbim umbim luci-proto-mbim
```

`kmod-usb-net-cdc-mbim` 会处理 USB net、usb-wdm、CDC-NCM 等内核依赖；`umbim` 还依赖 `libubox` 和 `wwan`，让 `opkg` 正常解析依赖。低闪存设备建议使用 Image Builder 将所需包纳入镜像。

确认内核日志显示实际的 `cdc_mbim` 绑定，并确认控制节点（常见为 `/dev/cdc-wdm0`）存在后，建立接口；APN、PIN、认证资料必须由运营商提供，下面只是字段示例：

```sh
uci set network.cellular='interface'
uci set network.cellular.proto='mbim'
uci set network.cellular.device='/dev/cdc-wdm0'
uci set network.cellular.apn='运营商提供的 APN'
# 可选字段：pincode auth username password pdptype ipv6 dhcp dhcpv6 delay mtu
uci set network.cellular.defaultroute='1'
uci set network.cellular.metric='20'
uci set network.cellular.peerdns='1'
uci commit network
ifdown cellular; ifup cellular
```

如不希望将 APN 或凭据留在 shell 历史中，请通过受控配置管理或 LuCI 输入，不要把含凭据的配置、诊断包或截图公开。

## USB：仅在实际绑定 qmi_wwan 时使用 QMI 备选

如果 `dmesg` 和 `lsmod` 显示设备实际由 `qmi_wwan` 绑定，而不是 `cdc_mbim`，可使用：

```sh
opkg update
opkg install kmod-usb-net-qmi-wwan uqmi luci-proto-qmi
uci set network.cellular='interface'
uci set network.cellular.proto='qmi'
uci set network.cellular.device='/dev/cdc-wdm0'
uci set network.cellular.apn='运营商提供的 APN'
uci commit network
ifdown cellular; ifup cellular
```

不要仅因控制节点也叫 `/dev/cdc-wdm0` 就混用两种协议、工具或 UCI `proto`；以实际内核绑定为准。

## PCI MHI：构建前检查

目标内核需要以下配置和相应 OpenWrt 包：

* `CONFIG_MHI_BUS` / `kmod-mhi-bus`
* `CONFIG_MHI_BUS_PCI_GENERIC` / `kmod-mhi-pci-generic`
* `CONFIG_WWAN` / `kmod-wwan`
* `CONFIG_MHI_WWAN_CTRL` / `kmod-mhi-wwan-ctrl`
* `CONFIG_MHI_WWAN_MBIM` / `kmod-mhi-wwan-mbim`

即使这些包存在，仍必须检查目标内核是否已有上述设备 ID，并在可恢复的测试设备上验证实际绑定。若目标源码缺少该项，才审核最小回移补丁并构建镜像。成功标准是内核实际创建并绑定了合适 WWAN/MBIM 控制与网络接口，随后再按 MBIM 的 UCI 原则配置；不是 `opkg` 的安装退出码。

## 验证和排错

```sh
ubus call network.interface.cellular status
ip link show
ip addr show
ip route show
ifdown cellular; ifup cellular
logread | tail -n 160
```

检查 `ubus` 状态、地址、默认路由和 DNS，再进行到公共地址的实际连通性测试。若没有绑定、没有控制节点或反复掉线，保留 `dmesg`/`logread`（先删去凭据）并回到“实际绑定”检查；不要强制加载不匹配的内核模块。

离线安装 `.ipk` 时，所有包和递归依赖必须来自**同一** OpenWrt 发布版本、target/subtarget、架构和内核 ABI。不得使用 `--force-depends` 掩盖 kmod ABI 不匹配。

## 一手资料

* [OpenWrt USB 内核模块定义](https://raw.githubusercontent.com/openwrt/openwrt/main/package/kernel/linux/modules/usb.mk)
* [umbim 包定义](https://raw.githubusercontent.com/openwrt/openwrt/main/package/network/utils/umbim/Makefile)
* [LuCI MBIM 协议](https://raw.githubusercontent.com/openwrt/luci/master/protocols/luci-proto-mbim/htdocs/luci-static/resources/protocol/mbim.js)
* [OpenWrt MHI 模块定义](https://raw.githubusercontent.com/openwrt/openwrt/main/package/kernel/linux/modules/other.mk) 与 [WWAN/MHI 网络模块](https://raw.githubusercontent.com/openwrt/openwrt/main/package/kernel/linux/modules/netdevices.mk)
* [上游 Linux MHI PCI ID 表](https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux.git/+/master/drivers/bus/mhi/host/pci_generic.c) 与 [引入 105b:e11d/e118 的提交](https://github.com/torvalds/linux/commit/bf30a75e6e00)
* [OpenWrt 蜂窝 WAN 指南](https://openwrt.org/docs/guide-user/network/wan/wwan/ltedongle) 与 [opkg 文档](https://openwrt.org/docs/guide-user/additional-software/opkg)
