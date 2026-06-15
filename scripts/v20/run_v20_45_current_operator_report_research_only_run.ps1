param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_45_current_operator_report_research_only_run.py"

Write-Host "STAGE_NAME=V20.45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
Write-Host "REPORT_GENERATION_ONLY=TRUE"
Write-Host "RESEARCH_ONLY_STATUS=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_TRADING_ALLOWED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_USED=FALSE"
Write-Host "PROVIDER_NETWORK_REFRESH_USED=FALSE"
Write-Host "OFFICIAL_RANKING_MUTATED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_MUTATED=FALSE"
Write-Host "REAL_PORTFOLIO_MUTATED=FALSE"
Write-Host "TRADING_SIGNAL_CREATED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.45 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_45_CURRENT_OPERATOR_REPORT_RESEARCH_ONLY_RUN"
}
finally {
    Pop-Location
}
