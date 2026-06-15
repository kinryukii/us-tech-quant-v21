param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_55_daily_one_click_research_runner.py"

Write-Host "STAGE_NAME=V20.55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
Write-Host "DAILY_ONE_CLICK_RESEARCH_ONLY_RUNNER=TRUE"
Write-Host "MARKET_REFRESH_ALLOWED_ONLY_THROUGH_APPROVED_V20_47_WRAPPER=TRUE"
Write-Host "V20_55_DIRECT_YFINANCE_IMPORT_USED=FALSE"
Write-Host "V20_55_DIRECT_PROVIDER_NETWORK_REFRESH_LOGIC_USED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_GENERATOR=FALSE"
Write-Host "TRADING_SIGNAL_GENERATOR=FALSE"
Write-Host "BUY_SELL_HOLD_INSTRUCTIONS_CREATED=FALSE"
Write-Host "BROKER_ORDER_SYSTEM_CONNECTED=FALSE"
Write-Host "TRADES_EXECUTED=FALSE"
Write-Host "RANKINGS_SCORES_FACTOR_WEIGHTS_DYNAMIC_WEIGHTS_REAL_BOOK_MUTATED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.55 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "PASS_V20_55_DAILY_ONE_CLICK_RESEARCH_RUNNER"
}
finally {
    Pop-Location
}
