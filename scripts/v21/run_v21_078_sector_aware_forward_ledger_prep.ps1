Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Report = Join-Path $Root "outputs\v21\v21_078\V21_078_R3_READINESS_DECISION_REPORT.csv"
Push-Location $Root
try {
    python (Join-Path $Dir "v21_078_sector_aware_forward_ledger_prep.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Report | Select-Object -First 1
    Write-Host "READINESS_DECISION_REPORT=$Report"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "POLICIES_IN_LEDGER=$($Row.portfolio_policies_in_forward_ledger)"
    Write-Host "LEDGER_ROWS=$($Row.ledger_rows)"
    exit 0
}
finally { Pop-Location }
