param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_46_current_market_refresh_readiness_gate.py"

Write-Host "STAGE_NAME=V20.46_CURRENT_MARKET_REFRESH_READINESS_GATE"
Write-Host "GATE_ONLY=TRUE"
Write-Host "REPORTING_ONLY=TRUE"
Write-Host "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_46=FALSE"
Write-Host "YAHOO_PROVIDER_PACKAGE_IMPORTED_IN_V20_46=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_USED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_TRADING_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_MUTATED=FALSE"
Write-Host "REAL_PORTFOLIO_MUTATED=FALSE"
Write-Host "RETURNS_CALCULATED=FALSE"
Write-Host "SCORES_RECOMPUTED=FALSE"
Write-Host "RANKINGS_RECOMPUTED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.46 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_46_CURRENT_MARKET_REFRESH_READINESS_GATE"
}
finally {
    Pop-Location
}
