# Contributing to DW5934e Open Source Project

Thank you for your interest in contributing to the **Dell Wireless DW5934e / Foxconn T99W640 / Qualcomm SDX72** open-source enablement project!

---

## 1. Safety & Legal Boundaries

1. **Never Commit Proprietary Firmware or Driver Binaries**:
   - Do NOT commit Qualcomm `.mbn`, `.bin`, `.dat` firmware images, Dell `.exe` setup packages, or proprietary driver binaries.
   - All tools and scripts must reference checksums, official download URLs, or dynamic extraction methods.
2. **Never Commit Private Device Identifiers or Credentials**:
   - Do NOT commit device-specific IMEIs, MEIDs, serial numbers, SIM IMSI/Kic keys, APN passwords, or private SSH keys.
   - All tests and sample configurations must use sanitized placeholder values (e.g., `000000000000000`, `example.apn`).
3. **Radio Frequency (RF) Safety & Compliance**:
   - Do not bypass regulatory power limits, SAR back-off tables, or disable safety shutdown mechanisms without explicit warnings and consent.
   - Emergency calling numbers (e.g. 110, 119, 120, 911, 112) must remain protected and never dialed by automated scripts.

---

## 2. Development Workflow

1. Fork the repository and create your feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Follow modular directory conventions:
   - `windows-installer/`: Windows 11 PowerShell/CMD installer logic.
   - `openwrt/`: OpenWrt feed packages, Makefiles, and auto-net scripts.
   - `linux-cellular-tools/`: QMI/MBIM userspace tools and voice control.
   - `flash-and-recovery/`: Flashing tools (`qdl`), state matrices, and recovery procedures.
   - `hardware-and-enclosure/`: CAD, 3D printing STEP/STL models, and mechanical documentation.
   - `research-reports/`: Forensic analysis, reverse-engineering papers, and bug reports.
3. Run existing tests before submitting PR:
   - Python tests: `python3 -m unittest` or `pytest`
   - OpenWrt package tests: `sh test_static.sh`
   - PowerShell tests: `Invoke-Pester` (or run `tests/Test-Contracts.ps1`)
4. Submit a Pull Request with a clear description of changes, verified hardware revisions, and test outcomes.
