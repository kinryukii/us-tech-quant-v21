param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_54_user_readable_current_decision_report.py"

Write-Host "STAGE_NAME=V20.54_USER_READABLE_CURRENT_DECISION_REPORT"
Write-Host "USER_READABLE_RESEARCH_ONLY_REPORT=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_CREATED=FALSE"
Write-Host "BUY_SELL_HOLD_INSTRUCTIONS_CREATED=FALSE"
Write-Host "TRADING_SIGNAL_CREATED=FALSE"
Write-Host "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_54=FALSE"
Write-Host "YFINANCE_IMPORT_USED_IN_V20_54=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_USED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "SCORE_RECOMPUTED=FALSE"
Write-Host "RANKINGS_RECOMPUTED=FALSE"
Write-Host "FACTOR_WEIGHT_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHT_MUTATED=FALSE"
Write-Host "REAL_BOOK_POSITION_MUTATED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.54 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_54_USER_READABLE_CURRENT_DECISION_REPORT"
}
finally {
    Pop-Location
}
