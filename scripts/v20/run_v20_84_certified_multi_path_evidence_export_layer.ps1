param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_84_certified_multi_path_evidence_export_layer.py"

Write-Host "STAGE_NAME=V20.84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT_LAYER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "OFFICIAL_WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
$Output = @()
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    $Allowed = @(
        "PASS_V20_84_CERTIFIED_MULTI_PATH_EVIDENCE_EXPORT",
        "PASS_V20_84_CERTIFIED_EVIDENCE_EXPORT_WITH_GAPS",
        "PASS_V20_84_R2_REQUIRED_EVIDENCE_PATHS_INTEGRATED",
        "PARTIAL_PASS_V20_84_R2_REQUIRED_PATHS_ATTACHED_WITH_BLOCKERS",
        "BLOCKED_V20_84_NO_USABLE_STRUCTURED_EVIDENCE",
        "BLOCKED_V20_84_UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT_DETECTED"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.84 did not report an allowed final status"
    }
    if ($ExitCode -ne 0 -and ($DetectedStatus -like "PASS_*" -or $DetectedStatus -like "PARTIAL_PASS_*")) {
        throw "V20.84 reported pass status with non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
    if ($DetectedStatus -like "BLOCKED_*") {
        exit 1
    }
}
catch {
    $PreservedStatus = $null
    if ($null -ne $Output) {
        $PreservedStatus = ($Output | Where-Object { $_ -match "^(PASS|PARTIAL_PASS|BLOCKED)_V20_84_" } | Select-Object -Last 1)
    }
    if ($PreservedStatus) {
        Write-Host $PreservedStatus
    }
    else {
        Write-Host "BLOCKED_V20_84_UNSAFE_OFFICIAL_OR_TRADE_ARTIFACT_DETECTED"
    }
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
