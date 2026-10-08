# Technical Research Reports and Reverse-Engineering Investigations

This directory archives reverse-engineering whitepapers, forensic investigation logs, and root-cause analyses conducted on the Dell Wireless 5934e (Qualcomm SDX72 / Foxconn T99W640) platform.

---

## Featured Reports

### `DW5934E_E11D_OEM_ROOT_FIX_REQUEST_20260822.md`
* **Title:** DW5934e E11D False PA Overheating Cellular Disconnection: OEM Root Fix Request
* **Summary:** Demonstrates why target modules experience cellular deregistration at ambient room temperature (~34°C) due to MPSS erroneously reporting `sdr0_pa` temperatures of 131–136°C.
* **Key Findings:**
  1. Traces the root cause to three invalid QPA therm logical associations (`ASIC 1 -> phy 4`, `ASIC 2 -> phy 6`, `ASIC 3 -> phy 10` instead of valid sensors `phy 3/12`) inside the `1183_0_0.mbn` RFC profile.
  2. Demonstrates why userspace/kernel hotpatches cannot solve the issue: MPSS DDR access is protected by Qualcomm XPU hardware access control blocks, and any non-OEM signed modification invalidates MBNv7 SHA-384 hashes and Foxconn OEM ECDSA-P384 digital signatures.
  3. Formulates a rigorous technical specification for OEM firmware rebuilds.
