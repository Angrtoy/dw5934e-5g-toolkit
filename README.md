# Dell Wireless 5934e (DW5934e) Open Source Project

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Linux | Windows | OpenWrt](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20OpenWrt-blue.svg)](#)
[![Qualcomm SDX72](https://img.shields.io/badge/Modem-Qualcomm%20Snapdragon%20X72%20(SDX72)-orange.svg)](#)
[![Foxconn T99W640](https://img.shields.io/badge/OEM-Foxconn%20T99W640-green.svg)](#)

**[English](README.md) | [中文说明 (Chinese)](README_CN.md)**

*A comprehensive engineering toolkit, automation suite, hardware mechanical models, and technical documentation for the Dell Wireless 5934e (Foxconn T99W640 / Qualcomm Snapdragon SDX72) 5G M.2 WWAN module.*

</div>

---

## Overview

The **Dell Wireless 5934e (DW5934e)** is a high-performance 5G Sub-6 / mmWave M.2 WWAN module engineered by Foxconn (model **T99W640**) and powered by the **Qualcomm Snapdragon X72 (SDX72)** modem platform.

While offering enterprise-grade 5G performance over PCIe MHI and USB CDC-MBIM interfaces, end-users, router builders, and embedded developers encounter significant hurdles:
- **Windows 11 Setup & FCC Lock:** Complex official installer dependencies, carrier configuration, and carrier FCC lock mechanisms.
- **Linux & OpenWrt Integration:** Kernel MHI bus driver binding (`mhi-pci-generic`), ModemManager compatibility, hotplug issues on routers like the Banana Pi BPI-R4 (MediaTek Filogic 880).
- **EDL Firmware Flashing & Recovery:** Risky emergency downloads without clear state boundaries between Dell composite EDL (`0489:e131`) and Qualcomm 9008 (`05c6:9008`).
- **Voice Calling Control Plane:** Lack of clean userspace tooling for VoLTE / IMS QMI call management via MBIM proxies.
- **Physical Integration & Heat Dissipation:** Adapting M.2 modules to USB/Ethernet boards and creating portable 5G CPE battery enclosures.
- **Hardware Thermal Anomalies:** Deep firmware bugs (such as false PA overheating reporting 136°C shutting down cellular).

This repository provides an **all-in-one open-source solution** covering deployment scripts, router packages, userspace tools, CAD designs, and in-depth forensic reports.

---

## Hardware Identity Matrix

| Mode / Endpoint | VID:PID | Subsystem | Description & Support Scope |
| :--- | :--- | :--- | :--- |
| **PCIe MHI (eSIM)** | `105b:e11d` | `105b:e11d` | Dell DW5934e with eSIM. Native MHI upstream support in Linux 6.11+. |
| **PCIe MHI (Non-eSIM)** | `105b:e11e` | `105b:e11e` | Dell DW5934e standard SIM slot. Supported by `dw5934e-autonet`. |
| **PCIe MHI (Foxconn)** | `105b:e118` | `105b:e118` | Foxconn T99W640 standard reference identity. |
| **PCIe Base ID** | `17cb:0309` | — | Qualcomm SDX72 hardware base / engineering recovery ID. |
| **USB Data Plane** | `05c6:90d5` | `MI_02` | USB CDC-MBIM interface (`netwmbclass` on Windows, `cdc_mbim` on Linux). |
| **Qualcomm EDL 9008** | `05c6:9008` | — | Emergency Download Mode (Sahara / Firehose). Handled via `qdl`. |
| **Dell Composite EDL** | `0489:e131` | — | Proprietary Dell EDL state. Stop immediately; do not treat as raw 9008. |

---

## Repository Structure

```text
dw5934e-open-source/
├── windows-installer/             # Windows 11 Conservative Automated Installer
│   ├── Install-DW5934e.cmd        # 1-click double-clickable batch launcher
│   ├── README.md                  # Windows installer manual & privacy specification
│   ├── docs/                      # Deployment, troubleshooting, and dev guides
│   ├── tests/                     # Pester / PowerShell contract test suite
│   └── windows/                   # PowerShell core engine, FCC helper, and manifests
│
├── openwrt/                       # OpenWrt & Router Enablement (BPI-R4 / MT7988)
│   ├── README.md                  # AutoNet feed manual & build instructions
│   ├── package/dw5934e-autonet/   # OpenWrt feed package definition & init service
│   ├── patches/                   # ModemManager wireless hotplug filter patches
│   ├── onekey-build.sh            # Automated compilation script for OpenWrt/QWRT
│   ├── router-install.sh          # Target router installation assistant
│   ├── build/                     # IPK dependency closure and kernel audit tools
│   ├── offline/                   # Offline bundle generator and deployment script
│   └── docs/                      # In-depth OpenWrt deployment whitepaper
│
├── linux-cellular-tools/          # Linux Userspace & Cellular QMI Tools
│   ├── voice-control/             # QMI VoLTE/IMS call-control utility (C / libqmi)
│   ├── voice-gui/                 # Desktop GUI dialer with Polkit privilege escalation
│   ├── nas-tools/                 # NAS domain preference and LTE-only experiment tools
│   ├── audio-observer/            # Audio endpoint and call routing observer
│   └── sim8202g-reference/        # SIM8202G companion tools (PDC profile, QMI, SMS)
│
├── flash-and-recovery/            # Firmware Maintenance & EDL Recovery
│   ├── README.md                  # Flashing guide, state matrix & stop conditions
│   ├── docs/                      # Ubuntu preparation, flashing, and FCC persistence
│   ├── tools/qdl-v2.7.1/          # Upstream Qualcomm EDL flashing utility (BSD-3-Clause)
│   ├── fcc/                       # FCC unlock persistence reference configurations
│   └── coldboot-scripts/          # Two-phase coldboot recovery scripts
│
├── hardware-and-enclosure/        # Mechanical Engineering & 3D Printing
│   ├── 5g-adapter-board/          # 5G M.2 to USB/RJ45 adapter STEP 3D model & specs
│   └── mf650-cpe-case/            # Aleca MF650 10000mAh portable 5G CPE case (CC BY-NC 4.0)
│       ├── build_mf650_cpe.py     # Parametric generation script
│       ├── design_v5_assembly_fixed/ # Production-ready STEP & STL 3D models
│       └── fit_coupon/            # Test fit coupons for SMA antenna holes
│
└── research-reports/              # In-Depth Engineering & Reverse-Engineering Papers
    ├── DW5934E_E11D_OEM_ROOT_FIX_REQUEST.md # Root cause report on false PA 136°C bug
    └── workflow-state/            # Historical RF and session recovery route maps
```

---

## Key Modules & Usage Guide

### 1. Windows 11 Conservative Installer (`windows-installer/`)

Designed as a **safe, zero-side-effect installer** that respects system integrity:
- **Dual Mode Execution:**
  - `Inventory Mode`: Strictly read-only. Scans PCI and USB endpoints without privilege escalation, file writes, or driver modifications.
  - `Install Mode`: Detects `105b:e11d` or `05c6:90d5:02`, verifies official Dell driver prerequisites (e.g., package `KNP7D A10`), installs drivers via `pnputil`, checks Windows inbox MBIM (`netwmbclass.inf`), and verifies FCC state.
- **Privacy & Sanitization:** Generates diagnostic reports without logging IMEI, MEID, serial numbers, phone numbers, or carrier APN credentials.

```powershell
# Run read-only inventory scan:
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-DW5934e.ps1 -Mode Inventory

# Run safe installation:
.\Install-DW5934e.cmd -Mode Install
```

---

### 2. OpenWrt Router Enablement (`openwrt/`)

Optimized for high-performance routers like the **Banana Pi BPI-R4 (MediaTek MT7988A / Filogic 880)** running OpenWrt / QWRT:
- Upstream kernel MHI drivers (`mhi-pci-generic`) binding PCIe `105b:e11d` / `105b:e11e`.
- Clean data plane: `MHI/WWAN -> ModemManager -> netifd proto modemmanager -> wan zone`.
- Prevents Wi-Fi hotplug storms from resetting cellular interfaces via targeted ModemManager patches.
- Offline deployment support via `offline/install.sh` and strict IPK dependency closure resolution.

```bash
# Add feed to your OpenWrt tree:
echo "src-link dw5934e_autonet /path/to/openwrt/package" >> feeds.conf.default
./scripts/feeds update dw5934e_autonet
./scripts/feeds install -p dw5934e_autonet dw5934e-autonet

# Build offline bundle:
DW_BOARD_NAME='bananapi,bpi-r4' ./onekey-build.sh /path/to/openwrt-tree
```

---

### 3. Linux QMI Voice Control Suite (`linux-cellular-tools/`)

Provides call control (dial, dial-ims, hangup, answer, voice domain query) over the QMI proxy:
- **Control-plane only:** Sends QMI requests without touching media streams.
- **Safety gates:** Emergency number blocking (110, 119, 120, 911, 112), digit validation, and mandatory `--confirm` tokens.
- **Resource hygiene:** Full asynchronous CID allocation and cleanup to prevent device lockups.
- **Desktop GUI:** Built-in Python/Tkinter GUI (`dw5934e_voice_gui.py`) with Polkit integration.

```bash
# Compile voice control tool:
gcc -Wall -Wextra -O2 dw5934e-voice-control.c -o dw5934e-voice-control $(pkg-config --cflags --libs qmi-glib)

# Query voice domain preference (read-only):
sudo ./dw5934e-voice-control voice-domain

# Dial a number:
sudo ./dw5934e-voice-control dial 10010 --confirm
```

---

### 4. Hardware CAD & MF650 CPE Enclosure (`hardware-and-enclosure/`)

- **5G Adapter Board:** Accurate STEP AP214 3D PCBA assembly model (`71.00 × 62.35 mm`, 1.6mm thickness) with Raspberry Pi 5 Active Cooler clearance (13.70mm).
- **Aleca MF650 10,000mAh Battery CPE Case:** Thickened enclosure (`160 × 90 × 37.9 mm`), 8-port SMA antenna array, front display window (`40.5 × 30.8 mm`), battery heat dissipation channels, and 3D printing slicing recommendations.

---

### 5. Technical Research & Root-Cause Bug Reports (`research-reports/`)

Contains formal investigation whitepapers:
- **`DW5934E_E11D_OEM_ROOT_FIX_REQUEST_20260822.md`**: Comprehensive forensic breakdown of the false PA overheating bug (`sdr0_pa` falsely reporting 131–136°C at room temperature 34°C, triggering CFCM shutdown). Proves why runtime overlays and NV modifications fail (XPU hardware isolation & OEM ECDSA-P384 signatures) and details the exact 1183 profile RFC thermal association fix required from OEMs.

---

## Security & Compliance Notice

- **No Proprietary Firmwares:** This repository contains no proprietary firmware images (`.mbn`, `.bin`, `.dat`) or official Dell `.exe` installers. All drivers must be downloaded directly from Dell official support.
- **Privacy First:** All test configurations, scripts, and logs are completely sanitized of real IMEIs, serial numbers, and private credentials.
- **RF Regulatory:** Use only in compliance with local radio regulatory policies.

---

## Licensing

- **Core Code & Scripts:** Licensed under the [MIT License](LICENSE).
- **QDL Utility:** Licensed under [BSD-3-Clause](flash-and-recovery/tools/qdl-v2.7.1/LICENSE).
- **MF650 3D Enclosure Design:** Licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) (Non-Commercial).
- See [NOTICE.md](NOTICE.md) for full attribution details.
