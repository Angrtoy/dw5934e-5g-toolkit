#requires -version 5.1
<#
  DW5934e Windows 11 installer.  Inventory is strictly read-only: it neither
  elevates nor writes logs/reports nor invokes a vendor package or PnP utility.
  Install/Repair only operate on one Dell-subsystem PCI E11D device.
#>
[CmdletBinding()]
param(
    [ValidateSet('Inventory','Install','Repair')][string]$Mode = 'Install',
    [string]$DriverPackagePath,
    [switch]$SkipFcc,
    [switch]$EnsureFcc,
    [switch]$IUnderstandFccTransaction
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$PackageName = 'Dell-Wireless-5934e-and-Qualcomm-Snapdragon-X72-Firmware_KNP7D_WIN64_0.1.0.32_A10.EXE'
$PackageSha256 = '63fe8a2605c81720e427aeaca47919a76a695f610a5222f83e6d22b2c0ce1d55'
$AllowedInfs = @('MhiHost.inf','QmuxMdm.inf','qcmbbnetadapter.inf')
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$FccSource = Join-Path $PSScriptRoot 'lib\\Dw5934e.Fcc.cs'
Import-Module (Join-Path $PSScriptRoot 'lib\\Classification.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'lib\\DeviceChecks.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'lib\\WindowsArgumentQuoting.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'lib\\FccResultPolicy.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'lib\\MbnIdentity.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'lib\\FccInvocationPolicy.psm1') -Force

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Get-ContainedPath([string]$Base, [string]$Candidate) {
    $fullBase = [IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $fullCandidate = [IO.Path]::GetFullPath($Candidate)
    if (-not $fullCandidate.StartsWith($fullBase, [StringComparison]::OrdinalIgnoreCase)) { throw "Refusing path outside controlled directory: $fullCandidate" }
    return $fullCandidate
}
function Get-SafePnpDevices {
    # Only instance IDs/hardware IDs needed for classification are read.  They
    # are never placed in the report because they can encode topology details.
    return @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Select-Object Status,Class,FriendlyName,InstanceId)
}
function Test-HardwareId([object]$Device, [string]$Pattern) {
    return ($Device.InstanceId -match $Pattern)
}
function Get-DeviceSnapshot {
    $devices = Get-SafePnpDevices
    $edl = @($devices | Where-Object { Test-HardwareId $_ '(?i)^USB\\VID_(05C6&PID_9008|0489&PID_E131)' })
    $e11d = @($devices | Where-Object { Test-HardwareId $_ '(?i)^PCI\\VEN_105B&DEV_E11D&SUBSYS_(E11D105B|105BE11D)' })
    $e118Pci = @($devices | Where-Object { Test-HardwareId $_ '(?i)^PCI\\VEN_105B&DEV_E118' })
    $e118UsbMbim = @($devices | Where-Object { Test-HardwareId $_ '(?i)^USB\\VID_05C6&PID_90D5&MI_02' })
    $moduleCount = $e11d.Count + $e118Pci.Count + $e118UsbMbim.Count
    $kind = 'none'
    if ($edl.Count -gt 0) { $kind = 'recovery' }
    elseif ($moduleCount -gt 1) { $kind = 'multiple' }
    elseif ($e11d.Count -eq 1) { $kind = 'e11d_pci' }
    elseif ($e118UsbMbim.Count -eq 1) { $kind = 'e118_usb_mbim' }
    elseif ($e118Pci.Count -eq 1) { $kind = 'e118_pci_unsupported' }
    $mbimInbox = $false
    if ($kind -eq 'e118_usb_mbim') {
        try {
            $driver = (Get-PnpDeviceProperty -InstanceId $e118UsbMbim[0].InstanceId -KeyName 'DEVPKEY_Device_DriverInfPath' -ErrorAction Stop)
            $mbimInbox = Test-E118InboxMbimDriverInf $driver
        } catch { $mbimInbox = $false }
    }
    $classification = Get-Dw5934eClassification -InstanceIds @($devices | ForEach-Object { $_.InstanceId }) -E118InboxMbim $mbimInbox
    $classification['Devices'] = $devices
    $classification['E11d'] = $e11d
    return $classification
}
function Find-VerifiedDellPackage([string]$ExplicitPath) {
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    if ($ExplicitPath) { $candidates.Add([IO.Path]::GetFullPath($ExplicitPath)) }
    $candidates.Add((Join-Path $Root "drivers\\$PackageName"))
    if ($env:USERPROFILE) { $candidates.Add((Join-Path $env:USERPROFILE "Downloads\\$PackageName")) }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        if ([IO.Path]::GetFileName($candidate) -cne $PackageName) { continue }
        $hash = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $PackageSha256) { continue }
        $signature = Get-AuthenticodeSignature -LiteralPath $candidate
        if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch '(?i)(^|,)CN=Dell Technologies Inc\.(,|$)') { continue }
        return [IO.Path]::GetFullPath($candidate)
    }
    throw "Dell package missing or verification failed. Supply only the documented KNP7D A10 package; no local INF or binary fallback is allowed."
}
function Invoke-WhitelistedDriverInstall([string]$PackagePath) {
    $programData = [IO.Path]::GetFullPath($env:ProgramData)
    $workRoot = Join-Path $programData 'DW5934e-installer\extracted'
    $stage = Join-Path $workRoot ([Guid]::NewGuid().ToString('N'))
    $stage = Get-ContainedPath $workRoot $stage
    New-Item -ItemType Directory -LiteralPath $stage -Force | Out-Null
    try {
        # Dell DUP driver-component extraction only.  Never invoke /driveronly,
        # the package install workflow, a firmware updater, or a fallback mode.
        & $PackagePath '/s' (('/drivers=' + $stage))
        if ($LASTEXITCODE -ne 0) { throw "Dell driver-component extraction failed (exit $LASTEXITCODE); refusing any fallback package workflow." }
        $driverRoot = Get-ContainedPath $stage (Join-Path $stage 'Production\Windows10-x64\22000\Drivers')
        foreach ($infName in $AllowedInfs) {
            $inf = Get-ContainedPath $driverRoot (Join-Path $driverRoot $infName)
            if (-not (Test-Path -LiteralPath $inf -PathType Leaf)) { throw "Verified package did not contain required INF: $infName" }
            # A whitelisted file is still inspected before pnputil. These three
            # network-path INFs must not contain firmware/MBFW update directives.
            $infText = [IO.File]::ReadAllText($inf)
            if ($infText -match '(?im)(firmware|mbfw|flash|updatefirmware|firmwareupdate)') { throw "Refusing INF with firmware/update content: $infName" }
            # pnputil is invoked with a fixed, audited INF name only.
            & pnputil.exe '/add-driver' $inf '/install'
            if ($LASTEXITCODE -ne 0) { throw "pnputil failed for approved INF $infName (exit $LASTEXITCODE)." }
        }
        & pnputil.exe '/scan-devices'
        if ($LASTEXITCODE -ne 0) { throw "pnputil rescan failed (exit $LASTEXITCODE)." }
    } finally {
        if (Test-Path -LiteralPath $stage) {
            $checked = Get-ContainedPath $workRoot $stage
            Remove-Item -LiteralPath $checked -Recurse -Force
        }
    }
}
function Get-MbnReady {
    try { $null = & netsh.exe mbn show interfaces 2>$null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Test-ParentChainIsDellE11d([string]$InstanceId) {
    $current = $InstanceId
    for ($depth = 0; $depth -lt 8; $depth++) {
        $parent = (Get-PnpDeviceProperty -InstanceId $current -KeyName 'DEVPKEY_Device_Parent' -ErrorAction Stop).Data
        if ([string]::IsNullOrWhiteSpace($parent)) { return $false }
        if ($parent -match '(?i)^PCI\\VEN_105B&DEV_E11D&SUBSYS_(E11D105B|105BE11D)') { return $true }
        if ($parent -eq $current) { return $false }
        $current = [string]$parent
    }
    return $false
}
function Invoke-GuardedFcc([System.Collections.IDictionary]$Snapshot) {
    if ($Snapshot.Kind -ne 'e11d_pci' -or $Snapshot.E11dCount -ne 1) { throw 'FCC transaction is restricted to one Dell-subsystem E11D PCI module.' }
    $qmuxPnp = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '(?i)QCQMUX_E11D105B' })
    if ($qmuxPnp.Count -ne 1) { throw 'Expected exactly one E11D QMUX PnP device.' }
    if (-not (Test-ParentChainIsDellE11d $qmuxPnp[0].InstanceId)) { throw 'QMUX parent chain does not lead to the unique Dell E11D PCI device.' }
    $rawMbn = (& netsh.exe mbn show interfaces 2>&1 | Out-String)
    $identityHash = Get-Dw5934eMbnIdentityHashFromText $rawMbn
    Clear-Variable rawMbn -ErrorAction SilentlyContinue
    if($null -eq $identityHash) { throw 'Unable to establish a unique named MBN Device ID identity guard.' }
    if (-not (Test-Path -LiteralPath $FccSource -PathType Leaf)) { throw 'Audited FCC source is missing.' }
    if ('Codex.Dw5934eFccNative' -as [type]) { throw 'FCC sender was already loaded; restart PowerShell and retry.' }
    Add-Type -TypeDefinition ([IO.File]::ReadAllText($FccSource)) -Language CSharp
    $guid = [Guid]'7dcb3244-c836-4a0c-a1e9-bd68d385aa2b'
    $interfaces = @([Codex.Dw5934eFccNative]::GetPresentDeviceInterfaces($guid) | Where-Object { $_ -match '(?i)#QcQmux_E11D105B#' })
    if ($interfaces.Count -ne 1) { throw 'Expected exactly one matching E11D QMUX interface.' }
    return [Codex.Dw5934eFccNative]::EnsureFcc($interfaces[0],$identityHash)
}

$report = [ordered]@{ Schema='dw5934e.beginner-installer.v1'; TimestampUtc=[DateTime]::UtcNow.ToString('o'); Mode=$Mode; ReadOnly=($Mode -eq 'Inventory'); DeviceKind=$null; ModuleCount=0; E118InboxMbim=$false; DriverPackageVerified=$false; DriverInstallAttempted=$false; WwanServiceRunning=$false; MbnQuerySucceeded=$false; FccRequested=$false; FccSkippedByUser=$false; FccDisposition=$null; FccVerified=$false; FccRollbackAttempted=$false; FccRollbackVerified=$false; ModuleWriteRequestsAttempted=0; ModuleWriteRequestsSent=0; ModuleWrites=0; Outcome='not_run'; Message=$null }
try {
    if ($Mode -ne 'Inventory' -and -not (Test-Administrator)) {
        $arguments = @('-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,'-Mode',$Mode)
        if ($DriverPackagePath) { $arguments += @('-DriverPackagePath',$DriverPackagePath) }
        if ($SkipFcc) { $arguments += '-SkipFcc' }
        if ($EnsureFcc) { $arguments += '-EnsureFcc' }
        if ($IUnderstandFccTransaction) { $arguments += '-IUnderstandFccTransaction' }
        $commandLine = Join-WindowsCommandLine -Arguments $arguments
        $child = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $commandLine -Wait -PassThru
        exit $child.ExitCode
    }
    $snapshot = Get-DeviceSnapshot
    $report.DeviceKind=$snapshot.Kind; $report.ModuleCount=$snapshot.ModuleCount; $report.E118InboxMbim=$snapshot.E118InboxMbim
    switch ($snapshot.Kind) {
        'recovery' { throw 'Recovery/EDL USB state detected. Stop: this installer does not perform recovery.' }
        'multiple' { throw 'More than one supported-module candidate is present. Stop: no driver or module write is safe.' }
        'none' { throw '未检测到受支持的模块。' }
        'e118_pci_unsupported' { throw 'E118 PCI was detected without a recognized USB MBIM MI_02 device. This PCI path is not supported by this installer.' }
        'e118_usb_mbim' { $report.MbnQuerySucceeded=Get-MbnReady; $report.Outcome='e118_usb_inbox_mbim_checked'; $report.Message='E118 USB 使用 Windows 自带 MBIM；未使用 Dell E11D 驱动或模块事务。'; break }
        'e11d_pci' {
            if ($Mode -eq 'Inventory') { $report.MbnQuerySucceeded=Get-MbnReady; $report.Outcome='inventory_complete'; $report.Message='E11D 只读盘点完成。'; break }
            $package = Find-VerifiedDellPackage $DriverPackagePath; $report.DriverPackageVerified=$true
            Invoke-WhitelistedDriverInstall $package; $report.DriverInstallAttempted=$true
            $svc = Get-Service -Name WwanSvc -ErrorAction Stop
            if ($svc.Status -ne 'Running') { Start-Service -Name WwanSvc }
            $report.WwanServiceRunning=((Get-Service -Name WwanSvc).Status -eq 'Running')
            $report.MbnQuerySucceeded=Get-MbnReady
            $fccPlan=Get-Dw5934eFccInvocationPlan -Mode $Mode -DeviceKind $snapshot.Kind -SkipFcc ([bool]$SkipFcc)
            if($fccPlan -eq 'user_skip') { $report.FccSkippedByUser=$true; $report.Outcome='driver_complete_state_skipped'; $report.Message='驱动步骤已完成；用户跳过模块状态检查，重启后可用 Repair 重试，蜂窝状态未验证。'; break }
            if($fccPlan -eq 'automatic') {
                $report.FccRequested=$true
                try { $fcc=Invoke-GuardedFcc $snapshot } catch { throw ('驱动步骤已完成，但 QMUX/MBN 状态检查无法开始；可能需重启后以 Repair 重试。原因：'+$_.Exception.Message) }
                $report.FccDisposition=$fcc.Disposition; $report.FccVerified=$fcc.Verified; $report.FccRollbackAttempted=$fcc.RollbackAttempted; $report.FccRollbackVerified=$fcc.RollbackVerified
                $report.ModuleWriteRequestsAttempted=$fcc.WriteRequestsAttempted; $report.ModuleWriteRequestsSent=$fcc.WriteRequestsSent; $report.ModuleWrites=$fcc.WriteRequestsSent
                $fccSucceeded=Test-Dw5934eFccGoalSucceeded -Disposition $fcc.Disposition -Verified $fcc.Verified -WriteAttempted $fcc.WriteAttempted -RollbackAttempted $fcc.RollbackAttempted
                if(-not $fccSucceeded) { $report.Outcome='driver_complete_fcc_failed'; $report.Message='驱动步骤已完成，但模块状态事务未达到验证成功状态。'; break }
            }
            $report.Outcome='install_or_repair_complete'; $report.Message='驱动流程完成；如运营商要求 APN，请仅在 Windows 设置中由用户配置。'; break
        }
    }
} catch {
    $report.Outcome='failed'; $report.Message=$_.Exception.Message
} finally {
    # Inventory deliberately has no file side effect.  Other modes write a
    # redacted report only; it contains no MBN identity, phone number, APN, or key.
    $report | ConvertTo-Json -Depth 5
    if ($Mode -ne 'Inventory') {
        try { $reportDir=Join-Path $env:ProgramData 'DW5934e-installer\reports'; New-Item -ItemType Directory -Force -Path $reportDir | Out-Null; $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportDir ('report-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'.json')) -Encoding UTF8 } catch { }
    }
}
if ($report.Outcome -in @('inventory_complete','e118_usb_inbox_mbim_checked','install_or_repair_complete')) { exit 0 } else { exit 1 }
