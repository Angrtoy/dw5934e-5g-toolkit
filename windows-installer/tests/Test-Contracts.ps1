#requires -version 5.1
[CmdletBinding()]
param()
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$here=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$installer=Join-Path $here 'windows\Install-DW5934e.ps1'
$csharp=Join-Path $here 'windows\lib\Dw5934e.Fcc.cs'
$openwrt=Join-Path $here 'docs\OPENWRT-DEPLOYMENT.md'
function Assert-True([bool]$Value,[string]$Message){if(-not $Value){throw $Message}}

# Every Windows PowerShell 5.1-loaded script/module is UTF-8 with BOM.  PS 7
# accepts the same encoding and the production .cmd explicitly launches 5.1.
$psSources=@(Get-ChildItem -LiteralPath (Join-Path $here 'windows') -Recurse -File | Where-Object {$_.Extension -in '.ps1','.psm1'}) + @(Get-Item -LiteralPath $PSCommandPath)
foreach($source in $psSources){$bytes=[IO.File]::ReadAllBytes($source.FullName);Assert-True ($bytes.Length -ge 3 -and $bytes[0]-eq 0xEF -and $bytes[1]-eq 0xBB -and $bytes[2]-eq 0xBF) ('UTF-8 BOM required: '+$source.FullName)}

foreach($source in $psSources){
    $tokens=$null; $errors=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile($source.FullName,[ref]$tokens,[ref]$errors)
    Assert-True ($errors.Count -eq 0) ('PowerShell AST errors in '+$source.FullName+': '+($errors | Out-String))
}
[void](Add-Type -TypeDefinition ([IO.File]::ReadAllText($csharp)) -Language CSharp -PassThru)

$scriptText=[IO.File]::ReadAllText($installer)
$csText=[IO.File]::ReadAllText($csharp)
$manifest=Get-Content -Raw -LiteralPath (Join-Path $here 'windows\manifests\dell-packages.json') | ConvertFrom-Json
Assert-True ($manifest.package.sha256 -ceq '63fe8a2605c81720e427aeaca47919a76a695f610a5222f83e6d22b2c0ce1d55') 'OEM package hash changed.'
Assert-True ($scriptText -match '/drivers=') 'DUP driver-component extraction is absent.'
Assert-True ($scriptText -notmatch '& \$PackagePath.*?/e=') 'Full-package extraction must not be invoked.'
Assert-True ($scriptText -notmatch '& \$PackagePath.*?/driveronly') 'DUP driveronly must not be invoked.'
Assert-True ($scriptText -match 'DEVPKEY_Device_DriverInfPath') 'E118 inbox check is not using DriverInfPath.'
Assert-True ($scriptText -notmatch "DEVPKEY_Device_Driver'") 'Ambiguous E118 Driver property remains.'
Assert-True ($scriptText -match 'Get-Dw5934eFccInvocationPlan' -and $scriptText -match "fccPlan -eq 'automatic'") 'Default E11D state invocation is absent.'
Assert-True ($scriptText -match 'SkipFcc' -and $scriptText -match 'driver_complete_state_skipped') 'Explicit state opt-out is absent or ambiguous.'
Assert-True ($csText -match 'WriteRequestsAttempted' -and $csText -match 'WriteRequestsSent' -and $csText -match 'RequestSent') 'Exact write accounting is incomplete.'
Assert-True ($csText -match 'already_unlocked_no_write' -and $csText -match 'action3_verified') 'Guarded state dispositions are incomplete.'
Assert-True ($csText -match 'IsAllowedRequest' -and $csText -match 'MESSAGE_SET_FCC') 'C# exact request allowlist is absent.'
Assert-True ($csText -notmatch 'RunFcc\(') 'Old transaction entrypoint remains.'

$badWords=@('FCC','unlock','解锁','0x5570','0x5571','disable_fcc_lock','FoxFlss')
$openText=[IO.File]::ReadAllText($openwrt)
foreach($word in $badWords){Assert-True ($openText.IndexOf($word,[StringComparison]::OrdinalIgnoreCase) -lt 0) "OpenWrt document contains forbidden text: $word"}
$binaries=@(Get-ChildItem -LiteralPath (Join-Path $here 'drivers') -File -Recurse | Where-Object {$_.Extension -match '(?i)^\.(exe|inf|sys|cat|dll)$'})
Assert-True ($binaries.Count -eq 0) 'OEM or driver binary was added to drivers/.'

Import-Module (Join-Path $here 'windows\lib\Classification.psm1') -Force
Import-Module (Join-Path $here 'windows\lib\DeviceChecks.psm1') -Force
Import-Module (Join-Path $here 'windows\lib\FccResultPolicy.psm1') -Force
Import-Module (Join-Path $here 'windows\lib\MbnIdentity.psm1') -Force
Import-Module (Join-Path $here 'windows\lib\WindowsArgumentQuoting.psm1') -Force
Import-Module (Join-Path $here 'windows\\lib\\FccInvocationPolicy.psm1') -Force

$fixtures=@(
    @{Name='e11d';Ids=@('PCI\VEN_105B&DEV_E11D&SUBSYS_E11D105B\X');Want='e11d_pci'},
    @{Name='e118-usb';Ids=@('USB\VID_05C6&PID_90D5&MI_02\X');Want='e118_usb_mbim'},
    @{Name='e118-pci';Ids=@('PCI\VEN_105B&DEV_E118&SUBSYS_00000000\X');Want='e118_pci_unsupported'},
    @{Name='edl';Ids=@('USB\VID_05C6&PID_9008\X');Want='recovery'},
    @{Name='multiple';Ids=@('PCI\VEN_105B&DEV_E11D&SUBSYS_E11D105B\X','USB\VID_05C6&PID_90D5&MI_02\Y');Want='multiple'},
    @{Name='none';Ids=@('USB\VID_1234&PID_5678\X');Want='none'}
)
foreach($fixture in $fixtures){$actual=Get-Dw5934eClassification -InstanceIds $fixture.Ids -E118InboxMbim $true;Assert-True ($actual.Kind -eq $fixture.Want) ("Fixture failed: "+$fixture.Name)}
Assert-True (Test-E118InboxMbimDriverInf ([pscustomobject]@{Data='netwmbclass.inf'})) 'Exact inbox INF should be ready.'
Assert-True (Test-E118InboxMbimDriverInf ([pscustomobject]@{Data='C:\Windows\INF\NETWMbClass.INF'})) 'Case-insensitive DriverInfPath should be ready.'
Assert-True (-not (Test-E118InboxMbimDriverInf ([pscustomobject]@{Data='oem42.inf'}))) 'Non-inbox INF must not be ready.'
Assert-True (-not (Test-E118InboxMbimDriverInf $null)) 'Missing DriverInfPath must not be ready.'
Assert-True (-not (Test-E118InboxMbimDriverInf ([pscustomobject]@{Data=@('netwmbclass.inf')}))) 'Ambiguous DriverInfPath must not be ready.'
Assert-True (Test-Dw5934eFccGoalSucceeded 'already_unlocked_no_write' $true $false $false) 'Already-unlocked no-write should succeed.'
Assert-True (Test-Dw5934eFccGoalSucceeded 'action3_verified' $true $true $false) 'Fully verified action3 should succeed.'
Assert-True (-not (Test-Dw5934eFccGoalSucceeded 'fcc_precondition_failed' $false $false $false)) 'Precondition failure must fail.'
Assert-True (-not (Test-Dw5934eFccGoalSucceeded 'fcc_failed_rolled_back_runtime_unlocked' $false $true $true)) 'Rollback result must not be a state-goal success.'
Assert-True (-not (Test-Dw5934eFccGoalSucceeded 'fcc_rollback_unverified' $false $true $true)) 'Unverified rollback must fail.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Install' 'e11d_pci' $false) -eq 'automatic') 'E11D Install must invoke state handling by default.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Repair' 'e11d_pci' $false) -eq 'automatic') 'E11D Repair must invoke state handling by default.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Inventory' 'e11d_pci' $false) -eq 'none') 'Inventory must never invoke state handling.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Install' 'e118_usb_mbim' $false) -eq 'none') 'E118 USB must never invoke E11D state handling.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Repair' 'e118_pci_unsupported' $false) -eq 'none') 'E118 PCI must never invoke E11D state handling.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Install' 'recovery' $false) -eq 'none') 'EDL must never invoke state handling.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Install' 'multiple' $false) -eq 'none') 'Multiple modules must never invoke state handling.'
Assert-True ((Get-Dw5934eFccInvocationPlan 'Install' 'e11d_pci' $true) -eq 'user_skip') 'Explicit E11D skip must be visible.'
$english='Device ID : 123456789012345'
$chinese='设备 ID : 123456789012345'
Assert-True ((Get-Dw5934eMbnIdentityHashFromText $english) -eq (Get-Dw5934eMbnIdentityHashFromText $chinese)) 'Named English/Chinese Device ID normalization differs.'
Assert-True ($null -eq (Get-Dw5934eMbnIdentityHashFromText 'unrelated: 123456789012345')) 'Unlabeled numeric text must not become identity.'
Assert-True ($null -eq (Get-Dw5934eMbnIdentityHashFromText ($english+"`n"+$english))) 'Multiple named Device IDs must fail closed.'

# This is a parser-only UAC command-line test: no Start-Process/UAC or device
# command is run. CommandLineToArgvW checks the exact argv transport boundary.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace DwInstallerTests {
 public static class NativeArgv {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr CommandLineToArgvW(string commandLine, out int argc);
  [DllImport("kernel32.dll")] public static extern IntPtr LocalFree(IntPtr hMem);
 }
}
'@ -Language CSharp
$argv=@('-NoLogo','-File','C:\含 空格\安装.ps1','-DriverPackagePath','C:\尾随 空格\quoted"name\','-SkipFcc','-EnsureFcc','-IUnderstandFccTransaction','')
$line=Join-WindowsCommandLine -Arguments $argv
$count=0; $ptr=[DwInstallerTests.NativeArgv]::CommandLineToArgvW($line,[ref]$count)
try { Assert-True ($ptr -ne [IntPtr]::Zero -and $count -eq $argv.Count) 'CommandLineToArgvW did not return expected argv count.'; for($i=0;$i -lt $count;$i++){ $actual=[Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::ReadIntPtr($ptr,$i*[IntPtr]::Size)); Assert-True ($actual -ceq $argv[$i]) ('Quoted argv mismatch at index '+$i) } }
finally { if($ptr -ne [IntPtr]::Zero){[void][DwInstallerTests.NativeArgv]::LocalFree($ptr)} }
Write-Host 'All static safety contracts, compilation, policy fixtures, and argv parser fixtures passed.'
