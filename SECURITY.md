# Security Policy

## 1. Supported Versions

Security and stability updates are applied to the latest commit on the `main` branch.

| Component | Status |
| :--- | :--- |
| Windows 11 Conservative Installer | Supported |
| OpenWrt `dw5934e-autonet` Package | Supported |
| Linux QMI Voice Control Suite | Supported |
| Flashing and Recovery Framework | Supported |

---

## 2. Reporting a Vulnerability

If you discover a security issue or privacy leak in any tool or documentation (such as accidental exposure of sensitive device identifiers, credentials, or dangerous command sequences), please report it responsibly:

* **Do NOT open a public GitHub issue.**
* Please submit a private advisory through GitHub's Security Advisories feature, or contact the project maintainers directly.
* Provide detailed steps to reproduce the issue and describe the potential impact.

---

## 3. Cellular and RF Safety Considerations

* **Emergency Numbers Protection:** Tools that issue call commands (`dw5934e-voice-control`) strictly enforce input verification to prevent accidental dialing of emergency dispatch numbers (e.g., 110, 112, 119, 120, 911). Modifying tools to bypass these restrictions is strictly discouraged.
* **Thermal and Power Gates:** The hardware features strict thermal thresholds managed by Qualcomm CFCM and RF profiles. Please do not force-disable thermal monitoring on production hardware without proper cooling dissipation.
