[CmdletBinding()]
param(
    [ValidateSet('Preflight','Apply','ActivateExisting','Rollback')][string]$Mode = 'Preflight',
    [string]$ConfirmToken = '',
    [string]$PdcExecutable = 'C:\Program Files (x86)\Qualcomm\QPST\bin\PDCCmdline.exe',
    [string]$Interface = '{A12BAE2C-C01D-4BE8-8E30-6DFA1B814AC9}_1',
    [string]$CandidatePath = 'C:\ProgramData\Codex\SIM8202G_CU_PDC_20260829\mcfg_sw.mbn',
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'artifacts'),
    [long]$ExpectedCandidateSize = 50580,
    [string]$ExpectedCandidateSha256 = 'cedb8f23ae2240e6103e7153c1f8ec7c0bd5f31eee8c1620aabb4b7609c0de96',
    [string]$ExpectedCuDescription = 'VoLTE-CU',
    [long]$ExpectedCuVersion = 167843169,
    [string]$BaselineHardwareId = '0AC5B18670A37720E8482E292879C9E8B99ACE0B',
    [string]$BaselineRowId = '804C2C464D18E001D88BBCA7B71B8F8F8556BAEA',
    [string]$BaselineRowDescription = 'ROW_Commercial',
    [long]$BaselineRowSize = 45700,
    [long]$BaselineRowVersion = 167839753,
    [int]$RecoveryTimeoutSeconds = 90
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'Sim8202gPdcTransaction.psm1') -Force

$ApplyToken = 'I-UNDERSTAND-PDC-APPLY-CU-20260829'
$ActivateExistingToken = 'I-UNDERSTAND-PDC-ACTIVATE-EXISTING-CU-20260829'
$RollbackToken = 'I-UNDERSTAND-PDC-ROLLBACK-ROW-20260829'
Assert-AsciiPath $PdcExecutable 'PdcExecutable'; Assert-AsciiPath $CandidatePath 'CandidatePath'; Assert-AsciiPath $OutputRoot 'OutputRoot'
if ($Interface -notmatch '^\{[0-9A-Fa-f-]{36}\}_1$') { throw 'Interface must be the exact ASCII {GUID}_1 control-file form' }
if (($Mode -eq 'Apply' -and $ConfirmToken -cne $ApplyToken) -or ($Mode -eq 'ActivateExisting' -and $ConfirmToken -cne $ActivateExistingToken) -or ($Mode -eq 'Rollback' -and $ConfirmToken -cne $RollbackToken)) { throw "Refusing ${Mode}: exact confirmation token is required" }

$run = Join-Path $OutputRoot ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $Mode.ToLowerInvariant())
New-Item -ItemType Directory -Force -Path $run | Out-Null
$candidateEvidence = $null
if ($Mode -ne 'Rollback') { $candidateEvidence = Get-CandidateAttestation $CandidatePath $ExpectedCandidateSize $ExpectedCandidateSha256 }
$manifest = [ordered]@{ mode=$Mode; started_utc=(Get-Date).ToUniversalTime().ToString('o'); interface=$Interface; candidate=$candidateEvidence; pdc_executable=$PdcExecutable; state='started' }
function Save-Manifest { $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $run 'manifest.json') -Encoding utf8NoBOM }
function List-Configs([string]$Name) { Parse-PdcList (Invoke-PdcChecked -Executable $PdcExecutable -PdcArgs @('-i',$Interface,'-l') -LogPath (Join-Path $run "$Name.txt")) }
function Invoke-Mutation([string[]]$MutationArgs, [string]$Name) { Invoke-PdcChecked -Executable $PdcExecutable -PdcArgs $MutationArgs -LogPath (Join-Path $run "$Name.txt") | Out-Null }
function Recovery-Command { "pwsh -NoProfile -File `"$PSCommandPath`" -Mode Rollback -ConfirmToken $RollbackToken" }

try {
    $interfaceText = Invoke-PdcChecked -Executable $PdcExecutable -PdcArgs @('-li') -LogPath (Join-Path $run 'interfaces-baseline.txt')
    if ($interfaceText -notmatch [regex]::Escape($Interface)) { throw 'Requested PDC control-file interface is absent from PDCCmdline -li output' }
    $baselineConfigs = List-Configs 'list-baseline'
    if ($Mode -in 'Preflight','Apply') {
        $alreadyPresent = @($baselineConfigs | Where-Object { $_.Description -eq $ExpectedCuDescription -and $_.Version -eq $ExpectedCuVersion -and $_.Size -eq $ExpectedCandidateSize })
        if ($alreadyPresent.Count -ne 0) { throw 'Expected CU candidate is already present before Load (pending/ambiguous state); refusing to continue' }
    }
    $baseline = Assert-ExpectedBaseline $baselineConfigs $BaselineHardwareId $BaselineRowId $BaselineRowDescription $BaselineRowVersion $BaselineRowSize -RequireSoftwareActive:($Mode -eq 'Preflight' -or $Mode -eq 'Apply' -or $Mode -eq 'ActivateExisting')
    $manifest.baseline = [ordered]@{ hardware_active_id=$baseline.Hardware.Id; row_id=$baseline.Software.Id; row_sub0=$baseline.Software.Sub0 }
    $manifest.state = 'preflight_verified'; Save-Manifest
    if ($Mode -eq 'Preflight') { Write-Output (Join-Path $run 'manifest.json'); exit 0 }

    if ($Mode -eq 'Apply') {
        Invoke-Mutation -MutationArgs @('-i',$Interface,'-Load',$CandidatePath) -Name '01-load'
        $afterLoad = List-Configs '02-list-after-load'
        $cu = Get-UniqueConfig $afterLoad $ExpectedCuDescription $ExpectedCuVersion $ExpectedCandidateSize
        $manifest.cu_id = $cu.Id; $manifest.state = 'candidate_uniquely_verified'; Save-Manifest
        Invoke-Mutation -MutationArgs @('-i',$Interface,'-s',$cu.Id,'0') -Name '03-set-sub0'
        Invoke-Mutation -MutationArgs @('-i',$Interface,'-a') -Name '04-activate'
        Wait-PdcInterface $PdcExecutable $Interface $run $RecoveryTimeoutSeconds
        $final = List-Configs '05-list-final'
        $verified = Get-UniqueConfig $final $ExpectedCuDescription $ExpectedCuVersion $ExpectedCandidateSize $cu.Id
        if ($verified.Sub0 -ne 'Active') { throw 'CU config is not active on Sub_0 after activation' }
        $manifest.state = 'apply_verified'; $manifest.completed_utc=(Get-Date).ToUniversalTime().ToString('o'); Save-Manifest; Write-Output (Join-Path $run 'manifest.json'); exit 0
    }

    if ($Mode -eq 'ActivateExisting') {
        # Strict resume path after a verified Load returned an error: no -Load,
        # no deactivate/remove, and no candidate selection by a caller-supplied ID.
        $cu = Get-UniqueConfig $baselineConfigs $ExpectedCuDescription $ExpectedCuVersion $ExpectedCandidateSize
        if ($cu.Sub0 -ne 'Inactive') { throw 'Existing CU must be uniquely present and Inactive on Sub_0 before activation resume' }
        $manifest.cu_id = $cu.Id; $manifest.state = 'existing_cu_uniquely_verified'; Save-Manifest
        Invoke-Mutation -MutationArgs @('-i',$Interface,'-s',$cu.Id,'0') -Name '01-set-existing-cu-sub0'
        Invoke-Mutation -MutationArgs @('-i',$Interface,'-a') -Name '02-activate-existing-cu'
        Wait-PdcInterface $PdcExecutable $Interface $run $RecoveryTimeoutSeconds
        $final = List-Configs '03-list-final'
        $verifiedCu = Get-UniqueConfig $final $ExpectedCuDescription $ExpectedCuVersion $ExpectedCandidateSize $cu.Id
        $verifiedRow = Get-UniqueConfig $final $BaselineRowDescription $BaselineRowVersion $BaselineRowSize $BaselineRowId
        if ($verifiedCu.Sub0 -ne 'Active' -or $verifiedRow.Sub0 -eq 'Active') { throw 'Existing CU activation verification failed (CU must be Active and ROW must not be Active on Sub_0)' }
        $manifest.state = 'activate_existing_verified'; $manifest.completed_utc=(Get-Date).ToUniversalTime().ToString('o'); Save-Manifest; Write-Output (Join-Path $run 'manifest.json'); exit 0
    }

    # Rollback deliberately selects/activates only the recorded baseline ROW ID; it never removes CU.
    $row = Get-UniqueConfig $baselineConfigs $BaselineRowDescription $BaselineRowVersion $BaselineRowSize $BaselineRowId
    Invoke-Mutation -MutationArgs @('-i',$Interface,'-s',$row.Id,'0') -Name '01-set-row-sub0'
    Invoke-Mutation -MutationArgs @('-i',$Interface,'-a') -Name '02-activate-row'
    Wait-PdcInterface $PdcExecutable $Interface $run $RecoveryTimeoutSeconds
    $final = List-Configs '03-list-final'
    $verified = Get-UniqueConfig $final $BaselineRowDescription $BaselineRowVersion $BaselineRowSize $BaselineRowId
    if ($verified.Sub0 -ne 'Active') { throw 'Baseline ROW is not active on Sub_0 after rollback activation' }
    $manifest.state = 'rollback_verified'; $manifest.completed_utc=(Get-Date).ToUniversalTime().ToString('o'); Save-Manifest; Write-Output (Join-Path $run 'manifest.json'); exit 0
} catch {
    $manifest.state = 'failed'; $manifest.failure = $_.Exception.Message; $manifest.recovery_command = Recovery-Command; Save-Manifest
    Write-Error "Transaction stopped: $($_.Exception.Message)"
    Write-Warning "No automatic rollback was attempted. If the device is usable and separate authorization is granted, review artifacts then run: $(Recovery-Command)"
    exit 1
}
