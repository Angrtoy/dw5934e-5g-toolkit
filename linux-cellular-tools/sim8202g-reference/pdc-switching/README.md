# SIM8202G CU PDC transaction preparation

> **Not authorized to run on the real module without a new, explicit user
> approval.** This directory prepares a narrowly constrained QPST
> `PDCCmdline.exe` workflow; it is not a recommendation to alter a modem.

## Fixed target facts

* executable: `C:\Program Files (x86)\Qualcomm\QPST\bin\PDCCmdline.exe`;
* PDC control file: `{A12BAE2C-C01D-4BE8-8E30-6DFA1B814AC9}_1`;
* baseline hardware Sub_0 active ID:
  `0AC5B18670A37720E8482E292879C9E8B99ACE0B` (`SS-SDX55`, version
  `167804928`);
* baseline software Sub_0 active ID:
  `804C2C464D18E001D88BBCA7B71B8F8F8556BAEA` (`ROW_Commercial`, size
  `45700`, version `167839753`);
* staged CU candidate:
  `C:\ProgramData\Codex\SIM8202G_CU_PDC_20260829\mcfg_sw.mbn`, exactly
  `50580` bytes and SHA-256
  `cedb8f23ae2240e6103e7153c1f8ec7c0bd5f31eee8c1620aabb4b7609c0de96`;
* expected loaded candidate: `VoLTE-CU`, version `167843169`, size `50580`.

All supplied paths must be absolute ASCII paths.  The tool never records
IMSI, ICCID, MSISDN, IMEI/MEID, or AT/QMI traffic.

## Modes and authorization boundary

### Default: `Preflight`

Default execution runs only QPST `-li` and `-i <interface> -l`, writes their
baseline artifacts, attests candidate size/SHA-256, parses complete
`START_CONFIG` blocks, and requires the stated HW and ROW IDs to be uniquely
active on Sub_0.  The parser explicitly recognizes QPST's empty-ID
`HW_DEFAULT` / `SW_DEFAULT` blocks only when all reported subscriptions are
`Default`; it marks them pseudo-configurations and excludes them from every
baseline, CU uniqueness, Set, Activate, and active-software check.  It performs
**no PDC mutation**.

```powershell
pwsh -NoProfile -File .\sim8202g_pdc_cu.ps1
```

### Apply (future, separately authorized only)

The script rejects Apply unless its exact, intentionally cumbersome token is
provided.  It never uses `-r` or `-d`.

```powershell
pwsh -NoProfile -File .\sim8202g_pdc_cu.ps1 `
  -Mode Apply -ConfirmToken I-UNDERSTAND-PDC-APPLY-CU-20260829
```

After preflight, the only mutation sequence is:

```text
Load candidate → list/save/parse → unique description+version+size match
→ Set candidate Sub_0 → Activate → wait for -li interface recovery
→ list and verify candidate Sub_0 Active
```

Any failure writes a manifest and prints a **manual** rollback command if the
module remains usable.  It does not automatically make a second destructive
choice, and it never removes CU.

### Resume an already loaded inactive CU (future, separately authorized only)

`ActivateExisting` exists only for the narrow case where a prior authorized
Load has already been independently observed in a saved list, but did not
reach Set/Activate. It has a different exact token:

```powershell
pwsh -NoProfile -File .\sim8202g_pdc_cu.ps1 `
  -Mode ActivateExisting `
  -ConfirmToken I-UNDERSTAND-PDC-ACTIVATE-EXISTING-CU-20260829
```

It first requires baseline HW and ROW still active, exactly one active
software configuration (ROW), and exactly one exact `VoLTE-CU` candidate with
a valid 40-hex ID and `Sub_0 Inactive`. It then performs only Set Sub_0 and
Activate, waits for interface recovery, and requires CU Active plus ROW not
Active. This mode contains no Load, Deactivate, or Remove command.

### Rollback (future, separately authorized only)

Rollback is separately token-gated:

```powershell
pwsh -NoProfile -File .\sim8202g_pdc_cu.ps1 `
  -Mode Rollback -ConfirmToken I-UNDERSTAND-PDC-ROLLBACK-ROW-20260829
```

It only sets the exact baseline ROW ID on Sub_0, activates subscriptions,
waits for interface recovery, and verifies ROW active.  It does not load,
deactivate, or remove CU.

## Offline tests only

No test invokes QPST or touches a real PDC device.  The test creates a temporary
fake `PDCCmdline` PowerShell program and synthetic PDC list, then exercises
parse, preflight, Apply and Rollback state transitions against that fake only:

```powershell
pwsh -NoProfile -File .\tests\run-tests.ps1
```

The test also asserts that fake execution saw Load/Set/Activate in the intended
flow and never saw `-r` or `-d`.
