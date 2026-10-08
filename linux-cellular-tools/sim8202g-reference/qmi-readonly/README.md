# SIM8202G Windows QMI-over-MBIM read-only diagnostic

## Scope and safety contract

This directory is deliberately a **public-API feasibility probe**, not a
general modem-control utility.  It targets the already supplied Windows MBN
interface GUID `A12BAE2C-C01D-4BE8-8E30-6DFA1B814AC9` for the `SimTech HS-USB
WWAN Adapter 9001`.

It is hard-bounded to:

* use the public `MobileBroadbandModem.CurrentNetwork.NetworkAdapter` GUID and
  its matching WWAN `ConnectionProfile` to identify the target and inspect its
  registration/connectivity state;
* inspect existing MBN connection/voice state where Windows exposes it;
* call the documented WinRT `MobileBroadbandModem.GetDefault()` and read its
  `DeviceServices` collection; and
* save only a redacted JSON report: status, public Device-Service GUIDs,
  capability booleans, and HRESULTs.  It does **not** save IMSI, ICCID,
  MSISDN, IMEI/MEID, serial number, or QMI response bytes.

The PowerShell script has **no** `SendQueryCommandAsync`,
`SendSetCommandAsync`, `OpenCommandSession`, `OpenDataSession`, serial, AT,
QPST, IOCTL, MBIM wire, PDC, or QMI transmission code.  In particular it
cannot dial, answer/end a call, start/stop packet data, scan/set NAS,
set/bind IMS/IMSA, change profiles, operate PDC, change NV/EFS/QCN/CNV, or
restart a module/driver/service.

It gates its real public-API enumeration on the target adapter's public WinRT
state being `Deregistered` with WWAN connectivity `None`, checks MBN
connection/voice states when connection objects exist, and refuses to continue
if `IsInEmergencyCallMode` is true.

## Why it stops at service enumeration

The documented Windows API accepts a Device-Service GUID, a **Device Service
command ID**, and bytes.  It does not document a universal raw-QMI passthrough:
QMI service/message/client/transaction fields are not Device-Service command
IDs.  A raw QMI request could only be considered if the driver actually
registers a Device-Service GUID and a vendor specification documents that
service's command and payload mapping.  If `DeviceServices` is empty, this is
positive blocking evidence; no driver bypass is permitted.

The relevant local SDK authority is:

* `C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\winrt\windows.networking.networkoperators.idl`
  (`IMobileBroadbandModem::DeviceServices`/`GetDeviceService`, and
  `SendQueryCommandAsync`);
* `...\um\mbnapi.idl` (`IMbnDeviceServicesManager`,
  `IMbnDeviceServicesContext`, and `IMbnDeviceService`).

Neither API contains an `ExecuteCommand` method.  The legacy COM API names
its asynchronous operation `QueryCommand`; the WinRT replacement names it
`SendQueryCommandAsync`.

## Run

From this directory, in a normal PowerShell session:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\sim8202g_qmi_readonly.ps1
```

The script prints the generated `results\\*.json` path.  Exit code `3` means a
safety preflight could not prove an idle target.  A successfully completed
enumeration that reports zero Device Services deliberately writes
`outcome: "blocked"` but exits `0`: this is the evidence-based public-API
feasibility stop, not a state-changing failure.

## Offline decoder test

`qmi_decode.py` never accesses a device.  It provides strict QMUX/TLV framing
checks and the two requested IMSA response message labels (0x0020 registration,
0x0021 services) from `analysis/vendor/libqmi/data/qmi-service-imsa.json`.

```powershell
python .\qmi_decode.py --self-test
python .\qmi_decode.py --hex 0111000021010201002000070002040000000000
```

The test frame is synthetic and contains only an IMSA success Result TLV.

## Present limitations

The tool does not claim that a visible Qualcomm/QPST PDC path is an MBN Device
Service, nor does it reuse or interfere with it.  A successful PDC read via a
vendor path demonstrates that *some* vendor transport exists, but does not
prove that Windows' public MBIM Device-Service abstraction exposes arbitrary
QMI.  When the report says `device_service_count: 0`, it is the documented
public API's actual enumeration result and the diagnostic stops there.
