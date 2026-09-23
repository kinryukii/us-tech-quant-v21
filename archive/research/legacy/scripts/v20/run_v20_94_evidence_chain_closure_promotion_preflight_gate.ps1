param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_94_evidence_chain_closure_promotion_preflight_gate.py"

Write-Host "STAGE_NAME=V20.94_EVIDENCE_CHAIN_CLOSURE_PROMOTION_PREFLIGHT_GATE"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "PROMOTION_ALLOWED=FALSE"
Write-Host "NASDAQ_HURDLE_PASSED=FALSE"
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
        "PASS_EVIDENCE_CHAIN_CLOSED_PROMOTION_STILL_BLOCKED",
        "BLOCKED_PROMOTION_PREFLIGHT_RESEARCH_ONLY",
        "BLOCKED_INSUFFICIENT_MULTI_RUN_HISTORY",
        "BLOCKED_OFFICIAL_RECOMMENDATION_NOT_READY",
        "BLOCKED_DYNAMIC_WEIGHT_NOT_PROMOTED",
        "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING"
    )
    $DetectedStatus = ($Output | Where-Object { $Allowed -contains $_ } | Select-Object -Last 1)
    if (-not $DetectedStatus) {
        throw "V20.94 did not report an allowed final status"
    }
    if ($ExitCode -ne 0 -and $DetectedStatus -ne "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING") {
        throw "V20.94 reported non-zero exit code $ExitCode"
    }
    Write-Host $DetectedStatus
    if ($DetectedStatus -eq "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING") {
        exit 1
    }
}
catch {
    $PreservedStatus = $null
    if ($null -ne $Output) {
        $PreservedStatus = ($Output | Where-Object { $_ -match "^(PASS|BLOCKED)_"} | Select-Object -Last 1)
    }
    if ($PreservedStatus) {
        Write-Host $PreservedStatus
    }
    else {
        Write-Host "BLOCKED_REQUIRED_EVIDENCE_CATEGORY_MISSING"
    }
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
