Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Report = Join-Path $Root "outputs\v21\v21_077\V21_077_R3_READINESS_DECISION_REPORT.csv"
Push-Location $Root
try {
    python (Join-Path $Dir "v21_077_sector_aware_risk_budget_backtest.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Report | Select-Object -First 1
    Write-Host "READINESS_DECISION_REPORT=$Report"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "POLICIES_TESTED=$($Row.policies_tested)"
    Write-Host "FEASIBLE_POLICIES=$($Row.feasible_policies)"
    Write-Host "RESEARCH_CANDIDATE_COUNT=$($Row.research_candidate_count)"
    exit 0
}
finally { Pop-Location }
