<#
.SYNOPSIS
  Public-API, read-only preflight and device-service enumeration for SIM8202G.

.DESCRIPTION
  This script deliberately has no SendQueryCommandAsync, SendSetCommandAsync,
  OpenCommandSession, OpenDataSession, PDC, AT, serial, or driver-IOCTL call.
  It proves whether Windows has registered a public Mobile Broadband Device
  Service before any future raw-QMI design is considered.  If none is exposed,
  it writes a redacted blocking result and stops.
#>
[CmdletBinding()]
param(
    [string]$InterfaceGuid = 'A12BAE2C-C01D-4BE8-8E30-6DFA1B814AC9',
    [string]$OutputPath = (Join-Path $PSScriptRoot ('results\device-service-enumeration-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'))
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Defined from the documented MbnApi SDK ABI only to inspect the *existing*
# connection objects' state.  Only read methods are invoked.
if (-not ('Sim8202gReadonlyMbn' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace Sim8202gReadonlyMbn {
 [ComImport, Guid("DCBBBAB6-201D-4BBB-AAEE-338E368AF6FA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 public interface IConnectionManager {
   [PreserveSig] int GetConnection([MarshalAs(UnmanagedType.LPWStr)] string id, [MarshalAs(UnmanagedType.Interface)] out IConnection connection);
   [PreserveSig] int GetConnections([MarshalAs(UnmanagedType.SafeArray, SafeArraySubType=VarEnum.VT_UNKNOWN)] out IConnection[] connections);
 }
 [ComImport, Guid("DCBBBAB6-200D-4BBB-AAEE-338E368AF6FA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
 public interface IConnection {
   [PreserveSig] int get_ConnectionID([MarshalAs(UnmanagedType.BStr)] out string value);
   [PreserveSig] int get_InterfaceID([MarshalAs(UnmanagedType.BStr)] out string value);
   // ABI placeholders for vtable slots 3 and 4.  They are never invoked;
   // their shapes are retained only so GetVoiceCallState remains at slot 6.
   [PreserveSig] int ReservedSlot3(int mode, [MarshalAs(UnmanagedType.LPWStr)] string profile, out uint requestId);
   [PreserveSig] int ReservedSlot4(out uint requestId);
   [PreserveSig] int GetConnectionState(out uint state, [MarshalAs(UnmanagedType.BStr)] out string profile);
   [PreserveSig] int GetVoiceCallState(out uint state);
 }
 [ComImport, Guid("BDFEE05C-4418-11DD-90ED-001C257CCFF1")]
 internal class ConnectionManagerCom {}
 public static class Safety {
   public static object[] GetConnections() {
     var manager = (IConnectionManager)new ConnectionManagerCom();
     IConnection[] connections; int hr = manager.GetConnections(out connections);
     if (hr < 0) return new object[] { hr, null };
     return new object[] { hr, connections };
   }
   public static object[] Describe(IConnection c) {
     string iface, ignoredProfile; uint connectionState, voiceState;
     int connectionHr=c.GetConnectionState(out connectionState, out ignoredProfile);
     int voiceHr=c.GetVoiceCallState(out voiceState);
     int ifaceHr=c.get_InterfaceID(out iface);
     return new object[] { ifaceHr, iface, connectionHr, connectionState, voiceHr, voiceState };
   }
 }
}
'@
}

function Convert-HResult([int]$HResult) {
    # PowerShell rejects a direct negative Int32 -> UInt32 conversion.
    $unsigned = if ($HResult -lt 0) { [uint64]([int64]$HResult + 0x100000000) } else { [uint64]$HResult }
    '0x{0:X8}' -f $unsigned
}
function Fail([string]$Reason, [hashtable]$Report) {
    $Report.outcome = 'blocked'
    $Report.block_reason = $Reason
    $parent = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $Report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path $OutputPath
    Write-Output $OutputPath
    exit 3
}

$report = [ordered]@{
    tool = 'sim8202g_qmi_readonly'
    timestamp_utc = (Get-Date).ToUniversalTime().ToString('o')
    target_interface_guid = $InterfaceGuid.ToUpperInvariant()
    safety_boundary = @(
      'public Windows Mobile Broadband/MBN read-only enumeration only',
      'no device-service command/data session is opened',
      'no QMI/MBIM/PDC/AT/IOCTL wire command is sent',
      'no dial, answer, end-call, packet connect/disconnect, scan, preference, IMS bind/set, or persistent write')
}

try {
    $modemType = [Windows.Networking.NetworkOperators.MobileBroadbandModem,Windows,ContentType=WindowsRuntime]
    $modem = $modemType::GetDefault()
    if ($null -eq $modem) { Fail 'Windows public MobileBroadbandModem.GetDefault returned null' $report }
    $network = $modem.CurrentNetwork
    if ($null -eq $network -or $null -eq $network.NetworkAdapter) { Fail 'default modem has no public network adapter for target verification' $report }
    $adapterGuid = $network.NetworkAdapter.NetworkAdapterId.ToString().ToUpperInvariant()
    $report.public_network_adapter_guid = $adapterGuid
    if ($adapterGuid -ne $InterfaceGuid.ToUpperInvariant()) { Fail 'Windows default modem does not map to the requested WWAN interface GUID' $report }
    $report.network_registration_state = [string]$network.NetworkRegistrationState
    $networkInformation = [Windows.Networking.Connectivity.NetworkInformation,Windows,ContentType=WindowsRuntime]
    $wwanProfiles = @($networkInformation::GetConnectionProfiles() | Where-Object {
        $_.IsWwanConnectionProfile -and $null -ne $_.NetworkAdapter -and $_.NetworkAdapter.NetworkAdapterId.ToString().ToUpperInvariant() -eq $adapterGuid
    })
    $report.target_wwan_connectivity_levels = @($wwanProfiles | ForEach-Object { [string]$_.GetNetworkConnectivityLevel() })
    if ($report.network_registration_state -ne 'Deregistered' -or @($wwanProfiles).Count -eq 0 -or @($report.target_wwan_connectivity_levels | Where-Object { $_ -ne 'None' }).Count -gt 0) {
        Fail 'target WWAN is not confirmed deregistered with connectivity None; no enumeration beyond safety gate' $report
    }
    $report.wwan_connection_state = 'not_connected'
    $report.emergency_call_mode = [bool]$modem.IsInEmergencyCallMode
    if ($report.emergency_call_mode) { Fail 'modem reports emergency-call mode; no device-service enumeration' $report }
} catch {
    Fail ('public Mobile Broadband safety preflight failed: ' + $_.Exception.GetType().FullName + ': ' + $_.Exception.Message) $report
}

$connections = [Sim8202gReadonlyMbn.Safety]::GetConnections()
$connectionHr = [int]$connections[0]
$report.mbn_connection_enumeration_hresult = Convert-HResult $connectionHr
$voiceStates = @()
if ($connectionHr -ge 0 -and $null -ne $connections[1]) {
    foreach ($connection in $connections[1]) {
        $item = [Sim8202gReadonlyMbn.Safety]::Describe($connection)
        # Only the requested interface and numeric state values are retained.
        if ($item[0] -ge 0 -and ([string]$item[1]).Trim('{}').ToUpperInvariant() -eq $InterfaceGuid.ToUpperInvariant()) {
            $voiceStates += [ordered]@{ connection_state = $item[3]; voice_state = $item[5]; connection_hresult = Convert-HResult([int]$item[2]); voice_hresult = Convert-HResult([int]$item[4]) }
        }
    }
}
$report.mbn_target_connection_states = $voiceStates
if (@($voiceStates).Count -gt 0 -and @($voiceStates | Where-Object { $_.connection_state -ne 0 -or $_.voice_state -ne 0 }).Count -gt 0) {
    Fail 'MBN reports a non-idle target connection or voice-call state; no enumeration beyond safety gate' $report
}
$report.voice_call_preflight = if (@($voiceStates).Count) { 'MBN target connection idle' } else { 'no MBN connection object; public WinRT state confirms target WWAN disconnected' }

try {
    $report.network_device_status = [string]$modem.DeviceInformation.NetworkDeviceStatus
    $services = @($modem.DeviceServices)
    $report.device_services = @($services | ForEach-Object {
        [ordered]@{ device_service_id = $_.DeviceServiceId.ToString(); data_read_supported = [bool]$_.IsDataReadSupported; data_write_supported = [bool]$_.IsDataWriteSupported }
    })
    $report.device_service_count = @($report.device_services).Count
} catch {
    Fail ('public Mobile Broadband API failed: ' + $_.Exception.GetType().FullName + ': ' + $_.Exception.Message) $report
}

if ($report.device_service_count -eq 0) {
    $report.outcome = 'blocked'
    $report.block_reason = 'Windows exposes zero Mobile Broadband Device Services for the default modem. The public API does not provide a generic raw-QMI channel, so no QMI client/session or wire request was created.'
} else {
    $report.outcome = 'enumerated_only'
    $report.block_reason = 'Device services were enumerated, but this safety-only tool intentionally does not open a session or send a command. A vendor-published mapping from the enumerated GUID/command IDs to QMI is required before any separate query tool may be designed.'
}
$parent = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$report | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path $OutputPath
Write-Output $OutputPath
