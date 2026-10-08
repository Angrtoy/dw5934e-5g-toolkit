# Third-Party Notices and Intellectual Property Acknowledgements

This project incorporates, interfaces with, or provides toolsets derived from several third-party software and hardware designs. Please review the licensing boundaries below:

---

## 1. Qualcomm EDL Tool (`qdl`)

* **Location:** `flash-and-recovery/tools/qdl-v2.7.1`
* **License:** BSD-3-Clause
* **Copyright:** (c) 2018-2024, Linaro Ltd., linux-msm contributors
* **Description:** The `qdl` tool is an open-source utility for communicating with Qualcomm devices in EDL (Emergency Download / Sahara / Firehose) mode. The full BSD-3-Clause license text is preserved in `flash-and-recovery/tools/qdl-v2.7.1/LICENSE`.

---

## 2. Dell Official Drivers and Qualcomm Firmware Blobs

* **Firmware and Drivers are NOT distributed in this repository.**
* Any Dell Windows driver executable (`.EXE`), Qualcomm firmware files (`.mbn`, `.bin`, `.dat`), and OEM radio profile packages belong to their respective rights holders (Dell Technologies Inc., Foxconn / Hon Hai Precision Industry Co., Ltd., Qualcomm Technologies, Inc.).
* This repository provides **clean, open-source automation scripts, verification tools, patch sets, and diagnostic documentation**. Users must acquire official driver packages (such as Dell package `KNP7D` / `THFC5`) directly from Dell official support channels.

---

## 3. Linux Kernel and OpenWrt

* Upstream Linux MHI bus generic driver contributions (`mhi-pci-generic`) are governed by GPL-2.0.
* OpenWrt feed package `dw5934e-autonet` is released under the MIT License, compatible with OpenWrt build infrastructure.
