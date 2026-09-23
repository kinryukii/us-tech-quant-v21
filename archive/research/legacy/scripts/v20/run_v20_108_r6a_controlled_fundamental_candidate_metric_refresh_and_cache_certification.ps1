param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_108_r6a_controlled_fundamental_candidate_metric_refresh_and_cache_certification.py"

Write-Host "STAGE_NAME=V20.108-R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_AND_CACHE_CERTIFICATION"
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
        throw "V20.108-R6A metric refresh certification failed with exit code $ExitCode"
    }
    $Passed = ($Output -contains "PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_CERTIFIED") -or
        ($Output -contains "PARTIAL_PASS_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_WITH_PARTIAL_COVERAGE") -or
        ($Output -contains "BLOCKED_V20_108_R6A_NO_FUNDAMENTAL_REFRESH_SOURCE_CONFIGURED") -or
        ($Output -contains "BLOCKED_V20_108_R6A_FUNDAMENTAL_REFRESH_FAILED")
    if (-not $Passed) {
        throw "V20.108-R6A metric refresh certification did not report accepted status"
    }
}
catch {
    Write-Host "BLOCKED_V20_108_R6A_CONTROLLED_FUNDAMENTAL_CANDIDATE_METRIC_REFRESH_AND_CACHE_CERTIFICATION"
    Write-Host "BLOCKER_REASON=$($_.Exception.Message)"
    exit 1
}
finally {
    Pop-Location
}
