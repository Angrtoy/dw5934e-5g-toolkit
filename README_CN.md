# Dell Wireless 5934e (DW5934e) 开源项目

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux | Windows | OpenWrt](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20OpenWrt-blue.svg)](#)
[![Qualcomm SDX72](https://img.shields.io/badge/Modem-Qualcomm%20Snapdragon%20X72%20(SDX72)-orange.svg)](#)
[![Foxconn T99W640](https://img.shields.io/badge/OEM-Foxconn%20T99W640-green.svg)](#)
[![Sponsor](https://img.shields.io/badge/赞助商-Discord%20Supporter-pink?logo=discord&logoColor=white)](https://discord.com/users/836215401431564299)

**[English (英文文档)](README.md) | [中文说明 (Chinese)](README_CN.md)**

*Dell Wireless 5934e（富士康 T99W640 / 高通骁龙 SDX72 / X72）5G M.2 WWAN 模块全套开源工程套件、自动化工具、路由器固件适配、硬件机械 3D 模型与深度分析资料*

</div>

---

## 项目背景与概述

**Dell Wireless 5934e (DW5934e)** 是一款由富士康代工（型号 **T99W640**）、搭载**高通骁龙 X72 (SDX72)** 芯片的企业级 5G Sub-6 / 毫米波 M.2 WWAN 模块。该模块支持 PCIe MHI 与 USB CDC-MBIM 双接口。

但在实际使用中，普通用户、软路由玩家与嵌入式开发者普遍面临诸多痛点：
1. **Windows 11 驱动安装与 FCC 解锁难：** 官方包依赖繁杂，驱动安装后容易出现网络服务未就绪、FCC 锁未激活或设备无法出网。
2. **OpenWrt / Linux 路由器适配门槛高：** 缺少开箱即用的 MHI 内核总线匹配、ModemManager 协同机制，在 Banana Pi BPI-R4（联发科 Filogic 880）等高端路由器上热插拔事件容易造成网卡反复复位。
3. **EDL 9008 固件维护与救砖缺乏状态边界：** 混淆高通 9008（`05c6:9008`）与戴尔复合 EDL（`0489:e131`），缺乏安全停止机制，极易导致模块永久损坏。
4. **缺少控制面通话工具：** 原生 MBIM 代理下缺少 VoLTE / IMS QMI 通话控制工具。
5. **硬件集成与结构参数：** 缺少匹配的 5G M.2 转接板 3D 机械模型，难以评估与被动/主动散热器的空间干涉。
6. **偶发假过热掉网故障：** 部分固件版本在常温（34°C）下 MPSS 误报 PA 高温（136°C）触发 CFCM 关机停网，缺乏深层逆向分析。

本项目将经过工程化检验的全套**开源驱动安装器、OpenWrt 自动拨号包、Linux QMI 通话工具、EDL 刷机工具链、转接板机械 3D 模型与逆向分析报告**统一整理开源，为 5G WWAN 社区提供标准、安全、合规的技术参考。

---

## 硬件识别与状态矩阵

| 模式 / 端点 | VID:PID | 子系统 ID | 说明与支持范围 |
| :--- | :--- | :--- | :--- |
| **PCIe MHI (eSIM 版)** | `105b:e11d` | `105b:e11d` | 戴尔 DW5934e 带 eSIM 版本。Linux 6.11+ 主线内核 `pci_generic.c` 已原生收录。 |
| **PCIe MHI (普通版)** | `105b:e11e` | `105b:e11e` | 戴尔 DW5934e 标准 SIM 卡槽版本。由本项目 `dw5934e-autonet` 原生支持。 |
| **PCIe MHI (富士康原厂)** | `105b:e118` | `105b:e118` | 富士康 T99W640 原厂工程/公版标识。 |
| **PCIe 基础恢复 ID** | `17cb:0309` | — | 高通 SDX72 底层引导 / 维护阶段硬件 ID。 |
| **USB 数据通道** | `05c6:90d5` | `MI_02` | USB CDC-MBIM 接口（Windows 对应 `netwmbclass`，Linux 对应 `cdc_mbim`）。 |
| **高通 EDL 9008** | `05c6:9008` | — | 紧急下载模式（Sahara / Firehose 协议），使用 `qdl` 进行受控恢复。 |
| **戴尔复合 EDL** | `0489:e131` | — | 戴尔私有复合 EDL 状态。**必须立即停止**，不可当成普通 9008 盲刷。 |

---

## 项目目录架构

```text
dw5934e-open-source/
├── windows-installer/             # Windows 11 保守型全自动安装器
│   ├── Install-DW5934e.cmd        # 双击以管理员身份运行的入口脚本
│   ├── README.md                  # 安装器设计理念、安全边界与隐私说明
│   ├── docs/                      # 部署、故障排除与二次开发文档
│   ├── tests/                     # Pester 契约自动化测试
│   └── windows/                   # PowerShell 引擎核心、FCC 辅助库与清单
│
├── openwrt/                       # OpenWrt / 路由器开箱即用支持包 (BPI-R4 / MT7988)
│   ├── README.md                  # AutoNet feed 详细使用与编译说明
│   ├── package/dw5934e-autonet/   # dw5934e-autonet 软件包 Makefile 与 init 服务
│   ├── patches/                   # ModemManager 抑制热插拔震荡内核补丁
│   ├── onekey-build.sh            # 一键编译脚本（自动分析依赖并闭环打包）
│   ├── router-install.sh          # 路由器端安装辅助脚本
│   ├── build/                     # IPK 依赖闭包解析与内核符号审计脚本
│   ├── offline/                   # 离线部署包生成器与安装程序
│   └── docs/                      # OpenWrt 部署与拨号深度指南
│
├── linux-cellular-tools/          # Linux 用户态蜂窝与通话控制工具集
│   ├── voice-control/             # C 语言编写的 QMI 通话控制工具 (libqmi)
│   ├── voice-gui/                 # Python/Tkinter 图形化通话拨号盘 (支持 Polkit)
│   ├── nas-tools/                 # NAS 域偏好与仅 LTE 实验工具
│   ├── audio-observer/            # 音频端点与通话状态监听器
│   └── sim8202g-reference/        # SIM8202G 参考脚本 (PDC 切换、QMI 监听、SMS)
│
├── flash-and-recovery/            # 固件维护与 EDL 9008 安全恢复流程
│   ├── README.md                  # 刷写流程、状态矩阵与停止规则
│   ├── docs/                      # Ubuntu 依赖准备、状态转移与 FCC 持久化
│   ├── tools/qdl-v2.7.1/          # 上游开源高通 EDL 刷机工具 (BSD-3-Clause)
│   ├── fcc/                       # FCC 解锁持久化配置样例
│   └── coldboot-scripts/          # AP047 两阶段冷启动恢复脚本
│
├── hardware-and-enclosure/        # 硬件机械资料与转接板 3D 模型
│   └── 5g-adapter-board/          # 5G M.2 转接板 STEP 3D PCBA 装配模型与尺寸参数
│
└── research-reports/              # 深度技术逆向与 OEM 根因报告
    ├── DW5934E_E11D_OEM_ROOT_FIX_REQUEST.md # 假 PA 136°C 掉网故障完整逆向报告
    └── workflow-state/            # 历史射频校准与会话恢复路线图
```

---

## 核心功能与使用指南

### 1. Windows 11 保守型安装器 (`windows-installer/`)

采用**保守型设计原则**：不修改固件、不擦写 NV、不强行修改 APN、零副作用。
- **盘点模式（Inventory Mode）：** 严格只读，不提权、不安装驱动、不写文件，仅输出设备硬件识别 JSON 状态。
- **安装模式（Install Mode）：** 识别 `105b:e11d` 或 `05c6:90d5:02`，验证官方 Dell 安装包（如 `KNP7D A10`），自动注入驱动，核查 Windows 原生 MBIM 驱动状态与蜂窝服务。
- **隐私保护：** 自动生成的脱敏报告绝不记录 IMEI、MEID、序列号、手机号或私有 APN 密钥。

```powershell
# 1. 运行只读检查（不写入系统）：
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-DW5934e.ps1 -Mode Inventory

# 2. 正常安全安装（需预先准备戴尔官方驱动包）：
.\Install-DW5934e.cmd -Mode Install
```

---

### 2. OpenWrt 路由器自动组网 (`openwrt/`)

针对 **Banana Pi BPI-R4 (MT7988A / Filogic 880)** 及各类基于 OpenWrt/QWRT 的 5G 路由器专门优化：
- 采用规范的数据平面分离：`MHI/WWAN -> ModemManager -> netifd proto modemmanager -> cellular -> wan zone`。
- 杜绝野蛮的 PCI `new_id` 强制绑定或厂商私有内核驱动崩溃。
- 提供内置补丁，彻底修复 Wi-Fi 热插拔事件导致 ModemManager 误断开网卡的问题。
- 支持离线打包与部署，自动进行 IPK 依赖闭包分析。

```bash
# 在 OpenWrt 源码树中添加 feed:
echo "src-link dw5934e_autonet /path/to/openwrt/package" >> feeds.conf.default
./scripts/feeds update dw5934e_autonet
./scripts/feeds install -p dw5934e_autonet dw5934e-autonet

# 构建离线部署套件：
DW_BOARD_NAME='bananapi,bpi-r4' ./onekey-build.sh /path/to/openwrt-tree
```

---

### 3. Linux QMI 通话控制工具集 (`linux-cellular-tools/`)

通过现有 MBIM 代理直接发送 QMI 通话控制（VoLTE / IMS）：
- **纯控制面：** 只负责信令控制（呼叫、接听、挂断、查询域偏好），不占用音频链路。
- **安全防误触机制：** 强制校验 3-32 位纯数字，**硬编码阻断所有国家/地区常见紧急号码（110、119、120、911、112）**，操作必须带 `--confirm` 参数。
- **资源清理卫生：** 退出时必定异步释放 CID 客户端并关闭 QMI 设备，防止设备通道死锁。
- **桌面图形界面：** 附带基于 Python/Tkinter 的跨平台图形拨号盘，集成系统 Polkit 鉴权。

```bash
# 编译通话控制工具：
gcc -Wall -Wextra -O2 dw5934e-voice-control.c -o dw5934e-voice-control $(pkg-config --cflags --libs qmi-glib)

# 只读查询语音域偏好 (CS / PS):
sudo ./dw5934e-voice-control voice-domain

# 发起呼叫 (需显式确认):
sudo ./dw5934e-voice-control dial 10010 --confirm
```

---

### 4. 机械工程资料与转接板模型 (`hardware-and-enclosure/`)

- **5G 转接板结构资料：** 包含 EasyEDA Pro 导出的完整 `Board` 装配 STEP 3D 模型（包络 `71.00 × 62.35 mm`，板厚 1.6mm），精准预留树莓派 5 散热器（Raspberry Pi 5 Active Cooler，总高度 13.70mm）避让空间。

---

### 5. 深度技术逆向报告 (`research-reports/`)

- **`DW5934E_E11D_OEM_ROOT_FIX_REQUEST_20260822.md`**：
  详细揭示了部分 DW5934e 模块在常温（34°C）下 MPSS 固件误将 `sdr0_pa` 采样上报为 131–136°C，进而触发 CFCM 热保护导致网络断开的深层根因。报告通过严格的逆向工程证实了 XPU 硬件隔离与 Foxconn OEM ECDSA-P384 签名机制限制，证明了内存热补丁不可行，并给出了明确的 OEM 1183 射频 Profile 热敏拓扑修正方案。

---

## 安全与开源规范说明

1. **不包含任何专有固件与商业驱动二进制：** 本仓库严格遵守知识产权法律，**绝不分发**高通专有固件（`.mbn`、`.bin`、`.dat`）或戴尔官方 `.exe` 驱动包。用户需直接前往戴尔官方服务支持网站下载官方固件包。
2. **严格脱敏与隐私保护：** 所有测试配置、测试日志已完全去除真实客户 IMEI、序列号、私有 IP 及运营商敏感凭证。
3. **无线电射频合规性：** 使用本套件时请遵守当地无线电管理法规。

---

## 💖 特别鸣谢与赞助商致谢 (Special Thanks & Sponsor)

<div align="center">

### 🌟 本项目的核心赞助者与鼎力支持者

在此怀着无比诚挚与感激的心情，向本项目的赞助商致以最崇高的谢意：

### 👉 **[Discord 赞助者主页：836215401431564299](https://discord.com/users/836215401431564299)** 👈

</div>

> [!NOTE]
> **致赞助商的衷心感谢信：**  
> 本项目能够从最初的实验室逆向分析、硬件测试样卡采购、转接底板工程测试，到全套 Windows 11 保守安装器、OpenWrt 路由器固件适配、Linux QMI 通话工具链、以及 5G 转接底板机械尺寸模型的完整落地与全面开源，**离不开赞助商始终如一的慷慨赞助、无比的信任与坚定支持！**
>
> 正是因为有您对开源精神与底层硬件工程的倾力投入，这项充满挑战的企业级 5G 模块攻关成果才得以跨越技术壁垒，毫无保留地公布给全球开发者与开源社区。  
> 
> **致以最由衷的感谢与敬意，感谢您让这一切成为现实！** 💐🙏✨

---

## 开源许可证

- **核心代码与脚本：** 遵循 [MIT License](LICENSE)。
- **QDL 刷机工具：** 遵循 [BSD-3-Clause](flash-and-recovery/tools/qdl-v2.7.1/LICENSE)。
- 详细第三方许可声明见 [NOTICE.md](NOTICE.md)。
- 详细第三方许可声明见 [NOTICE.md](NOTICE.md)。
