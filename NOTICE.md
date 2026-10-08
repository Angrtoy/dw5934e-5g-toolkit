# Third-Party Notices and Intellectual Property Acknowledgements

This project incorporates, interfaces with, or provides toolsets derived from several third-party software and hardware designs. Please review the licensing boundaries below:

---

## 1. Qualcomm EDL Tool (`qdl`)

* **Location:** `flash-and-recovery/tools/qdl-v2.7.1`
* **License:** BSD-3-Clause
* **Copyright:** (c) 2018-2024, Linaro Ltd., linux-msm contributors
* **Description:** The `qdl` tool is an open-source utility for communicating with Qualcomm devices in EDL (Emergency Download / Sahara / Firehose) mode. The full BSD-3-Clause license text is preserved in `flash-and-recovery/tools/qdl-v2.7.1/LICENSE`.

---

## 2. Aleca MF650 3D Enclosure Design

* **Location:** `hardware-and-enclosure/mf650-cpe-case`
* **License:** [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/)
* **Original Author:** 滴滴 (Model ID 979284)
* **Derivative Work:** Parametric modifications, thickened shell profiles (160 × 90 × 37.9 mm), 8-hole SMA antenna backplate, and DFAM (Design for Additive Manufacturing) engineering enhancements.
* **Usage Restrictions:** Derivative models and files in this subfolder are strictly non-commercial. Commercial sale of printed enclosures requires separate rights from original copyright holders.

---

## 3. Dell Official Drivers and Qualcomm Firmware Blobs

* **Firmware and Drivers are NOT distributed in this repository.**
* Any Dell Windows driver executable (`.EXE`), Qualcomm firmware files (`.mbn`, `.bin`, `.dat`), and OEM radio profile packages belong to their respective rights holders (Dell Technologies Inc., Foxconn / Hon Hai Precision Industry Co., Ltd., Qualcomm Technologies, Inc.).
* This repository provides **clean, open-source automation scripts, verification tools, patch sets, and diagnostic documentation**. Users must acquire official driver packages (such as Dell package `KNP7D` / `THFC5`) directly from Dell official support channels.

---

## 4. Linux Kernel and OpenWrt

* Upstream Linux MHI bus generic driver contributions (`mhi-pci-generic`) are governed by GPL-2.0.
* OpenWrt feed package `dw5934e-autonet` is released under the MIT License, compatible with OpenWrt build infrastructure.
