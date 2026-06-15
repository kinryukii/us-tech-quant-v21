param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_39_r2_shadow_weighted_entry_strategy_backtest.py"

Write-Host "STAGE_NAME=V20.39-R2_SHADOW_WEIGHTED_ENTRY_STRATEGY_BACKTEST"
Write-Host "SHADOW_ONLY=TRUE"
Write-Host "EXPLORATORY_RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "TRADING_SIGNAL_CREATED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_CODE_CREATED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "OFFICIAL_FACTOR_WEIGHTS_MUTATED=FALSE"
Write-Host "OFFICIAL_FACTOR_PROMOTION_CREATED=FALSE"
Write-Host "OFFICIAL_STRATEGY_PROMOTED=FALSE"
Write-Host "OFFICIAL_DYNAMIC_WEIGHTING_STARTED=FALSE"
Write-Host "PORTFOLIO_BACKTEST_CREATED=FALSE"
Write-Host "EQUITY_CURVE_CREATED=FALSE"
Write-Host "PERFORMANCE_CLAIMS_CREATED=FALSE"
Write-Host "CURRENT_TOP20_USED_FOR_HISTORICAL_BACKTEST=FALSE"
Write-Host "NON_PIT_FACTORS_EXCLUDED=TRUE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.39-R2 stage failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
