param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r7_strategy_candidate_score_source_builder.py"

Write-Host "STAGE_NAME=V20.108-R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER"
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
        throw "V20.108-R7 strategy source builder failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER_WITH_PARTIAL_COVERAGE") -or
        ($Output -contains "BLOCKED_V20_108_R7_NO_SAFE_STRATEGY_CANDIDATE_SOURCE_FOUND")
    if (-not $Passed) {
        throw "V20.108-R7 did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R7_STRATEGY_CANDIDATE_SCORE_SOURCE_BUILDER"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
