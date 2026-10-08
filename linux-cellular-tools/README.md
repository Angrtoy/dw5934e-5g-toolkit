# Linux Cellular and Voice Tools

This directory contains specialized userspace utilities for managing cellular call control, voice domains, and radio preferences on the Dell Wireless 5934e (Qualcomm SDX72 / Foxconn T99W640).

---

## Directory Contents

| Tool | Language | Description |
| :--- | :--- | :--- |
| `voice-control/` | C / libqmi | Control-plane QMI call management (dial, dial-ims, hangup, answer, voice domain query) via MBIM QMI proxy. |
| `voice-gui/` | Python / Tkinter | Graphical desktop dialer integrating with `dw5934e-voice-control` and Polkit privilege elevation. |
| `nas-tools/` | C / Bash | Query and modify NAS domain usage preferences and LTE-only preference experiment scripts. |
| `audio-observer/` | Shell / Python | Voice audio endpoint state and call session observer. |
| `sim8202g-reference/` | Python / PowerShell | Reference scripts for companion testing (SIM8202G-M2 PDC profile switching, QMI inspection, SMS). |

---

## Safety Guarantees

* **Emergency Calling Protection:** `voice-control` strictly blocks calls to emergency numbers (`110`, `119`, `120`, `911`, `112`).
* **Resource Cleanup:** All QMI clients properly issue `RELEASE_CID` and close handles on exit/signals to prevent modem descriptor leakages.
