Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Report = Join-Path $Root "outputs\v21\v21_080\V21_080_R2_READINESS_DECISION_REPORT.csv"
Push-Location $Root
try {
    python (Join-Path $Dir "v21_080_entry_exit_vs_qqq_10k_report.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Report | Select-Object -First 1
    Write-Host "READINESS_DECISION_REPORT=$Report"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "STRATEGIES_COMPARED=$($Row.strategies_compared)"
    exit 0
}
finally { Pop-Location }
