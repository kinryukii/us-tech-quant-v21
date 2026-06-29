Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Report = Join-Path $Root "outputs\v21\v21_081\V21_081_R3_READINESS_DECISION_REPORT.csv"
Push-Location $Root
try {
    python (Join-Path $Dir "v21_081_soft_execution_policy_backtest.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Report | Select-Object -First 1
    Write-Host "READINESS_DECISION_REPORT=$Report"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "BEST_SOFT_EXECUTION_POLICY=$($Row.best_soft_execution_policy)"
    exit 0
}
finally { Pop-Location }
