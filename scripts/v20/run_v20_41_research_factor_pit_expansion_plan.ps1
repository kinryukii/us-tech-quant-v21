param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_41_research_factor_pit_expansion_plan.py"

Write-Host "STAGE_NAME=V20.41_RESEARCH_FACTOR_PIT_EXPANSION_PLAN"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "TRADING_SIGNAL_CREATED=FALSE"
Write-Host "BROKER_ORDER_PATH_CREATED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_EXECUTED=FALSE"
Write-Host "PORTFOLIO_BACKTEST_RERUN=FALSE"
Write-Host "NEW_RETURN_COMPUTATION_CREATED=FALSE"
Write-Host "PROVIDER_REFRESH_EXECUTED=FALSE"
Write-Host "HISTORICAL_SOURCE_BACKFILL_EXECUTED=FALSE"
Write-Host "PRIOR_ACCEPTED_OUTPUTS_MUTATED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"
Write-Host "READY_FOR_OFFICIAL_TRADING_OR_RECOMMENDATION=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.41 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
