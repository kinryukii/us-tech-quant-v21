param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r6b_fundamental_candidate_score_materializer_with_partial_coverage.py"

Write-Host "STAGE_NAME=V20.108-R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE"
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
        throw "V20.108-R6B materializer failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_EXCLUSIONS") -or
        ($Output -contains "BLOCKED_V20_108_R6B_NO_CERTIFIED_FUNDAMENTAL_METRICS_AVAILABLE")
    if (-not $Passed) {
        throw "V20.108-R6B did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R6B_FUNDAMENTAL_CANDIDATE_SCORE_MATERIALIZER_WITH_PARTIAL_COVERAGE"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
