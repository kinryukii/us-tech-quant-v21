param(
    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v20_44_daily_operator_report_acceptance_gate_or_current_run.py"

Write-Host "STAGE_NAME=V20.44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN"
Write-Host "REPORTING_OR_GATE_ONLY=TRUE"
Write-Host "DRY_RUN_ONLY=TRUE"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_RECOMMENDATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_TRADING_ALLOWED=FALSE"
Write-Host "BROKER_ORDER_EXECUTION_PATH=FALSE"
Write-Host "PROVIDER_REFRESH_EXECUTED=FALSE"
Write-Host "NETWORK_REFRESH_EXECUTED=FALSE"
Write-Host "DYNAMIC_WEIGHTING_EXECUTED=FALSE"
Write-Host "REAL_PORTFOLIO_MUTATED=FALSE"
Write-Host "V21_OUTPUTS_CREATED=FALSE"
Write-Host "V19_21_OUTPUTS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    & $Python $StageScript
    if ($LASTEXITCODE -ne 0) {
        throw "V20.44 stage failed with exit code $LASTEXITCODE"
    }
    Write-Host "FINAL_STATUS=PASS_V20_44_DAILY_OPERATOR_REPORT_ACCEPTANCE_GATE_OR_CURRENT_RUN"
}
finally {
    Pop-Location
}
