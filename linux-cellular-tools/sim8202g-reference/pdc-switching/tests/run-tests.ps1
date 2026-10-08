$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $root 'Sim8202gPdcTransaction.psm1') -Force

$sample = @'
START_CONFIG
Description     : SS-SDX55
Type            : Hardware
Size            : 20100
Version         : 167804928
ID              : 0AC5B18670A37720E8482E292879C9E8B99ACE0B
Sub_0 Status : Active
END_CONFIG
START_CONFIG
Description     : ROW_Commercial
Type            : Software
Size            : 45700
Version         : 167839753
ID              : 804C2C464D18E001D88BBCA7B71B8F8F8556BAEA
Sub_0 Status : Active
END_CONFIG
'@
$parsed = Parse-PdcList $sample
if ($parsed.Count -ne 2) { throw 'Parser did not return exactly two configs' }
$baseline = Assert-ExpectedBaseline $parsed '0AC5B18670A37720E8482E292879C9E8B99ACE0B' '804C2C464D18E001D88BBCA7B71B8F8F8556BAEA' 'ROW_Commercial' 167839753 45700 -RequireSoftwareActive
if ($baseline.Software.Id -ne '804C2C464D18E001D88BBCA7B71B8F8F8556BAEA') { throw 'Baseline parser assertion failed' }
try { Parse-PdcList 'START_CONFIG`nDescription : only`nEND_CONFIG' | Out-Null; throw 'Malformed list was accepted' } catch { if ($_.Exception.Message -eq 'Malformed list was accepted') { throw } }
$realShape = Parse-PdcList (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fixtures\pdc-list-with-defaults.txt') -Raw)
$pseudo = @($realShape | Where-Object IsPseudoDefault)
if ($pseudo.Count -ne 2 -or @($pseudo | Where-Object { $_.Id -ne $null -or $_.Sub0 -ne 'Default' }).Count -ne 0) { throw 'HW_DEFAULT/SW_DEFAULT pseudo blocks were not strictly marked' }
$realBaseline = Assert-ExpectedBaseline $realShape '0AC5B18670A37720E8482E292879C9E8B99ACE0B' '804C2C464D18E001D88BBCA7B71B8F8F8556BAEA' 'ROW_Commercial' 167839753 45700 -RequireSoftwareActive
if ($realBaseline.Hardware.IsPseudoDefault -or $realBaseline.Software.IsPseudoDefault) { throw 'Pseudo-default block entered baseline selection' }

$temp = Join-Path ([IO.Path]::GetTempPath()) ('sim8202g-pdc-fake-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    $candidate = Join-Path $temp 'mcfg_sw.mbn'; [IO.File]::WriteAllBytes($candidate, [byte[]](1,2,3,4,5))
    $sha = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    $fake = Join-Path $temp 'FakePdc.ps1'; $state = Join-Path $temp 'state.txt'; $calls = Join-Path $temp 'calls.txt'
    @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$PdcArgs)
$state = Join-Path $PSScriptRoot 'state.txt'; $calls=Join-Path $PSScriptRoot 'calls.txt'
Add-Content -LiteralPath $calls -Value ($PdcArgs -join '|')
if ($PdcArgs -contains '-li') { "Control File Name: {A12BAE2C-C01D-4BE8-8E30-6DFA1B814AC9}_1"; exit 0 }
if ($PdcArgs -contains '-Load') { Set-Content $state 'loaded'; exit 0 }
if ($PdcArgs -contains '-s') { if ($PdcArgs -contains 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC') { Set-Content $state 'cu-selected' } else { Set-Content $state 'row-selected' }; exit 0 }
if ($PdcArgs -contains '-a') { $s=Get-Content $state -ErrorAction SilentlyContinue; if($s -eq 'cu-selected'){Set-Content $state 'cu-active'} elseif($s -eq 'row-selected'){Set-Content $state 'row-active'}; exit 0 }
$s=Get-Content $state -ErrorAction SilentlyContinue
$active = if($s -eq 'cu-active'){'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC'}else{'804C2C464D18E001D88BBCA7B71B8F8F8556BAEA'}
@"
START_CONFIG
Description : SS-SDX55
Type : Hardware
Size : 20100
Version : 167804928
ID : 0AC5B18670A37720E8482E292879C9E8B99ACE0B
Sub_0 Status : Active
END_CONFIG
START_CONFIG
Description : ROW_Commercial
Type : Software
Size : 45700
Version : 167839753
ID : 804C2C464D18E001D88BBCA7B71B8F8F8556BAEA
Sub_0 Status : $(if($active -like '804C*'){'Active'}else{'Inactive'})
END_CONFIG
$(if($s){@"
START_CONFIG
Description : VoLTE-CU
Type : Software
Size : 5
Version : 7
ID : CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
Sub_0 Status : $(if($active -like 'CCCC*'){'Active'}else{'Inactive'})
END_CONFIG
"@})
"@
'@ | Set-Content -LiteralPath $fake -Encoding utf8NoBOM
    $tool = Join-Path $root 'sim8202g_pdc_cu.ps1'; $output = Join-Path $temp 'artifacts'
    & (Join-Path $PSHOME 'pwsh.exe') -NoProfile -File $tool -Mode Apply -ConfirmToken 'wrong-token' -PdcExecutable $fake -CandidatePath $candidate -OutputRoot $output -ExpectedCandidateSize 5 -ExpectedCandidateSha256 $sha -ExpectedCuVersion 7 -RecoveryTimeoutSeconds 1 2>$null
    if ($LASTEXITCODE -eq 0 -or (Test-Path -LiteralPath $calls)) { throw 'Invalid Apply token reached the fake PDC executable' }
    & $tool -Mode Preflight -PdcExecutable $fake -CandidatePath $candidate -OutputRoot $output -ExpectedCandidateSize 5 -ExpectedCandidateSha256 $sha -ExpectedCuVersion 7 -RecoveryTimeoutSeconds 1
    if ($LASTEXITCODE -ne 0) { throw 'Fake preflight failed' }
    & $tool -Mode Apply -ConfirmToken 'I-UNDERSTAND-PDC-APPLY-CU-20260829' -PdcExecutable $fake -CandidatePath $candidate -OutputRoot $output -ExpectedCandidateSize 5 -ExpectedCandidateSha256 $sha -ExpectedCuVersion 7 -RecoveryTimeoutSeconds 1
    if ($LASTEXITCODE -ne 0) { throw 'Fake apply failed' }
    & $tool -Mode Rollback -ConfirmToken 'I-UNDERSTAND-PDC-ROLLBACK-ROW-20260829' -PdcExecutable $fake -CandidatePath $candidate -OutputRoot $output -ExpectedCandidateSize 5 -ExpectedCandidateSha256 $sha -ExpectedCuVersion 7 -RecoveryTimeoutSeconds 1
    if ($LASTEXITCODE -ne 0) { throw 'Fake rollback failed' }
    # Simulate an earlier successful Load which stopped before Set/Activate.
    Set-Content -LiteralPath $state -Value 'loaded'
    $beforeResume = (Get-Content -LiteralPath $calls -Raw).Length
    & $tool -Mode ActivateExisting -ConfirmToken 'I-UNDERSTAND-PDC-ACTIVATE-EXISTING-CU-20260829' -PdcExecutable $fake -CandidatePath $candidate -OutputRoot $output -ExpectedCandidateSize 5 -ExpectedCandidateSha256 $sha -ExpectedCuVersion 7 -RecoveryTimeoutSeconds 1
    if ($LASTEXITCODE -ne 0) { throw 'Fake ActivateExisting failed' }
    $callText = Get-Content -LiteralPath $calls -Raw
    foreach ($required in '-Load','|-s|','|-a') { if ($callText -notmatch [regex]::Escape($required)) { throw "Fake command log lacks $required" } }
    if ($callText -match '(^|\|)-(r|d)(\||$)') { throw 'Test observed a forbidden remove/deactivate command' }
    if ($callText.IndexOf('-Load') -gt $callText.IndexOf('|-s|') -or $callText.IndexOf('|-s|') -gt $callText.IndexOf('|-a')) { throw 'Fake command ordering is not Load -> Set -> Activate' }
    $resumeCalls = $callText.Substring($beforeResume)
    if ($resumeCalls -match '-Load|(^|\|)-(r|d)(\||$)' -or $resumeCalls -notmatch '\|-s\|' -or $resumeCalls -notmatch '\|-a') { throw 'ActivateExisting was not strictly Set/Activate-only' }
    Write-Output 'PDC parser/state-machine fake test: PASS'
} finally { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
