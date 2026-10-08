Set-StrictMode -Version Latest

function Assert-AsciiPath {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Label)
    if ($Path -match '[^\x00-\x7F]') { throw "$Label must be an ASCII path: $Path" }
    if (-not [IO.Path]::IsPathFullyQualified($Path)) { throw "$Label must be an absolute path: $Path" }
}

function ConvertTo-CanonicalId {
    param([Parameter(Mandatory)][string]$Id)
    $value = ($Id -replace '\s', '').ToUpperInvariant()
    if ($value -notmatch '^[0-9A-F]{40}$') { throw "PDC ID is not a 40-digit hexadecimal SHA-1-style ID: '$Id'" }
    return $value
}

function Get-CandidateAttestation {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][long]$ExpectedSize,
          [Parameter(Mandatory)][string]$ExpectedSha256)
    Assert-AsciiPath $Path 'CandidatePath'
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Candidate does not exist: $Path" }
    $file = Get-Item -LiteralPath $Path
    if ($file.Length -ne $ExpectedSize) { throw "Candidate size mismatch: expected $ExpectedSize, got $($file.Length)" }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $ExpectedSha256.ToLowerInvariant()) { throw 'Candidate SHA-256 mismatch' }
    [pscustomobject]@{ Path = $file.FullName; Size = $file.Length; Sha256 = $actual }
}

function Parse-PdcList {
    <# Parses only PDCCmdline START_CONFIG blocks. Unknown surrounding output is ignored. #>
    param([Parameter(Mandatory)][string]$Text)
    $blocks = [regex]::Matches($Text, '(?ms)^START_CONFIG\s*$\r?\n(.*?)^END_CONFIG\s*$')
    if ($blocks.Count -eq 0) { throw 'PDCCmdline list contains no complete START_CONFIG/END_CONFIG blocks' }
    $configs = foreach ($block in $blocks) {
        $body = $block.Groups[1].Value
        $fields = @{}
        foreach ($line in ($body -split "`r?`n")) {
            if ($line -match '^\s*(Config Index|Description|Type|Size|Version|ID)\s*:\s*(.*?)\s*$') { $fields[$matches[1]] = $matches[2] }
            if ($line -match '^\s*Sub_(\d+)\s+Status\s*:\s*(Active|Inactive|Default)\s*$') { $fields["Sub_$($matches[1])"] = $matches[2] }
        }
        foreach ($required in 'Description','Type','Size','Version','ID') { if (-not $fields.ContainsKey($required)) { throw "Malformed PDC block missing $required" } }
        if ($fields['Size'] -notmatch '^\d+$' -or $fields['Version'] -notmatch '^\d+$') { throw 'Malformed numeric Size or Version in PDC block' }
        $description = $fields['Description']; $type = $fields['Type']; $rawId = $fields['ID'].Trim(); $sub0 = ($fields['Sub_0'] ?? 'Unknown')
        $isPseudoDefault = (($description -eq 'HW_DEFAULT' -and $type -eq 'Hardware') -or ($description -eq 'SW_DEFAULT' -and $type -eq 'Software'))
        if ($isPseudoDefault) {
            $subStatuses = @($fields.Keys | Where-Object { $_ -match '^Sub_\d+$' } | ForEach-Object { $fields[$_] })
            if ($rawId.Length -ne 0 -or $subStatuses.Count -eq 0 -or @($subStatuses | Where-Object { $_ -ne 'Default' }).Count -ne 0) { throw "Malformed $description pseudo-default block" }
            [pscustomobject]@{ Description=$description; Type=$type; Size=[long]$fields['Size']; Version=[long]$fields['Version']; Id=$null; Sub0=$sub0; IsPseudoDefault=$true }
        } else {
            if ($rawId.Length -eq 0 -or $sub0 -eq 'Default') { throw "Non-default PDC config '$description' has an empty ID or Default Sub_0 state" }
            [pscustomobject]@{ Description=$description; Type=$type; Size=[long]$fields['Size']; Version=[long]$fields['Version']; Id=(ConvertTo-CanonicalId $rawId); Sub0=$sub0; IsPseudoDefault=$false }
        }
    }
    return @($configs)
}

function Get-UniqueConfig {
    param([Parameter(Mandatory)][object[]]$Configs, [Parameter(Mandatory)][string]$Description,
          [Parameter(Mandatory)][long]$Version, [Parameter(Mandatory)][long]$Size, [string]$Id)
    $matches = @($Configs | Where-Object { -not $_.IsPseudoDefault -and $_.Description -eq $Description -and $_.Version -eq $Version -and $_.Size -eq $Size -and ( [string]::IsNullOrEmpty($Id) -or $_.Id -eq (ConvertTo-CanonicalId $Id) ) })
    if ($matches.Count -ne 1) { throw "Expected exactly one config '$Description' version $Version size $Size; found $($matches.Count)" }
    return $matches[0]
}

function Assert-ExpectedBaseline {
    param([Parameter(Mandatory)][object[]]$Configs,
          [Parameter(Mandatory)][string]$HardwareId, [Parameter(Mandatory)][string]$SoftwareId,
          [Parameter(Mandatory)][string]$SoftwareDescription, [Parameter(Mandatory)][long]$SoftwareVersion,
          [Parameter(Mandatory)][long]$SoftwareSize, [switch]$RequireSoftwareActive)
    $hardware = @($Configs | Where-Object { -not $_.IsPseudoDefault -and $_.Id -eq (ConvertTo-CanonicalId $HardwareId) -and $_.Type -eq 'Hardware' })
    if ($hardware.Count -ne 1 -or $hardware[0].Sub0 -ne 'Active') { throw 'Expected baseline hardware configuration is not uniquely active on Sub_0' }
    $software = Get-UniqueConfig $Configs $SoftwareDescription $SoftwareVersion $SoftwareSize $SoftwareId
    if ($RequireSoftwareActive -and $software.Sub0 -ne 'Active') { throw 'Expected baseline ROW configuration is not active on Sub_0' }
    $activeSoftware = @($Configs | Where-Object { -not $_.IsPseudoDefault -and $_.Type -eq 'Software' -and $_.Sub0 -eq 'Active' })
    if ($activeSoftware.Count -ne 1) { throw "Expected exactly one active Sub_0 software config; found $($activeSoftware.Count)" }
    return [pscustomobject]@{ Hardware=$hardware[0]; Software=$software }
}

function Invoke-PdcChecked {
    param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string[]]$PdcArgs,
          [Parameter(Mandatory)][string]$LogPath)
    Assert-AsciiPath $Executable 'PdcExecutable'
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "PDCCmdline executable not found: $Executable" }
    $output = & $Executable @PdcArgs 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Set-Content -LiteralPath $LogPath -Value $output -Encoding utf8NoBOM
    if ($exitCode -ne 0) { throw "PDCCmdline failed (exit $exitCode): $($PdcArgs -join ' ')" }
    return $output
}

function Wait-PdcInterface {
    param([Parameter(Mandatory)][string]$Executable, [Parameter(Mandatory)][string]$Interface,
          [Parameter(Mandatory)][string]$LogDirectory, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $log = Join-Path $LogDirectory ('interface-wait-' + (Get-Date -Format 'HHmmssfff') + '.txt')
        try {
            $text = Invoke-PdcChecked -Executable $Executable -PdcArgs @('-li') -LogPath $log
            if ($text -match [regex]::Escape($Interface)) { return }
        } catch { }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    throw "PDC interface did not reappear within $TimeoutSeconds seconds"
}

Export-ModuleMember -Function Assert-AsciiPath,ConvertTo-CanonicalId,Get-CandidateAttestation,Parse-PdcList,Get-UniqueConfig,Assert-ExpectedBaseline,Invoke-PdcChecked,Wait-PdcInterface
