param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_95_promotion_blocker_decomposition_multi_run_sufficiency_plan.py"

Write-Host "STAGE_NAME=V20.95_PROMOTION_BLOCKER_DECOMPOSITION_MULTI_RUN_SUFFICIENCY_PLAN"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "PROMOTION_ALLOWED=FALSE"
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
        "PASS_V20_95_PROMOTION_BLOCKERS_DECOMPOSED_RESEARCH_ONLY",
        "WARN_V20_95_PROMOTION_BLOCKERS_DECOMPOSED_WITH_MISSING_OPTIONAL_INPUTS",
        "BLOCKED_V20_95_EVIDENCE_CHAIN_NOT_CLOSED"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.95 did not report an allowed final status"
    }
    if ($ExitCode -ne 0 -and $DetectedStatus -ne "BLOCKED_V20_95_EVIDENCE_CHAIN_NOT_CLOSED") {
        throw "V20.95 reported non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
    if ($DetectedStatus -eq "BLOCKED_V20_95_EVIDENCE_CHAIN_NOT_CLOSED") {
        exit 1
    }
}
catch {
    $PreservedStatus = $null
    if ($null -ne $Output) {
        $PreservedStatus = ($Output | Where-Object { $_ -match "^(PASS|WARN|BLOCKED)_V20_95_" } | Select-Object -Last 1)
    }
    if ($PreservedStatus) {
        Write-Host $PreservedStatus
    }
    else {
        Write-Host "BLOCKED_V20_95_EVIDENCE_CHAIN_NOT_CLOSED"
    }
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
