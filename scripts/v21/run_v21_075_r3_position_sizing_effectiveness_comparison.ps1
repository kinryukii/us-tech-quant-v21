Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Validation = Join-Path $Root "outputs\v21\v21_075\V21_075_R3_VALIDATION_SUMMARY.csv"
Push-Location $Root
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Dir "run_v21_075_r2_ranking_only_portfolio_backtest.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $Dir "v21_075_r3_position_sizing_effectiveness_comparison.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "BEST_RAW_RETURN_POLICY=$($Row.best_raw_return_policy)"
    Write-Host "BEST_RISK_ADJUSTED_POLICY=$($Row.best_risk_adjusted_policy)"
    exit 0
}
finally { Pop-Location }
