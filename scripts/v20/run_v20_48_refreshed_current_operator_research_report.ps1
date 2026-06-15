param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_48_refreshed_current_operator_research_report.py"

Write-Host "STAGE_NAME=V20.48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
Write-Host "REPORT_GENERATION_ONLY=TRUE"
Write-Host "REFRESHED_V20_47_CACHE_USED=TRUE"
Write-Host "PROVIDER_NETWORK_REFRESH_EXECUTED_IN_V20_48=FALSE"
Write-Host "YFINANCE_IMPORT_USED_IN_V20_48=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_USED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_TRADING_ALLOWED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_MUTATED=FALSE"
Write-Host "RETURNS_CALCULATED=FALSE"
Write-Host "SCORES_RECOMPUTED=FALSE"
Write-Host "RANKINGS_RECOMPUTED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.48 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_48_REFRESHED_CURRENT_OPERATOR_RESEARCH_REPORT"
}
finally {
    Pop-Location
}
