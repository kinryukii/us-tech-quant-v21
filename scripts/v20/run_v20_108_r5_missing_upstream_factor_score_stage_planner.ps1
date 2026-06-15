param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r5_missing_upstream_factor_score_stage_planner.py"

Write-Host "STAGE_NAME=V20.108-R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_PROMOTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "IS_OFFICIAL_RANKING=FALSE"
Write-Host "IS_OFFICIAL_WEIGHT=FALSE"
Write-Host "WEIGHT_MUTATED=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"
Write-Host "BROKER_EXECUTION_SUPPORTED=FALSE"

Push-Location $RepoRoot
try {
    $Output = & $Python $StageScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | ForEach-Object { Write-Host $_ }
    if ($ExitCode -ne 0) {
        throw "V20.108-R5 planner failed with exit code $ExitCode"
    }
    if (-not ($Output -contains "PASS_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER")) {
        throw "V20.108-R5 planner did not report pass status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R5_MISSING_UPSTREAM_FACTOR_SCORE_STAGE_PLANNER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
