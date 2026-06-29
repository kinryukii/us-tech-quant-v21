Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
$Validation = Join-Path $Root "outputs\v21\v21_076\V21_076_R3_READINESS_DECISION_REPORT.csv"
Push-Location $Root
try {
    python (Join-Path $Dir "v21_076_pit_sector_industry_classification_audit.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "READINESS_DECISION_REPORT=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "SECTOR_COVERAGE_RATE=$($Row.sector_coverage_rate)"
    Write-Host "INDUSTRY_COVERAGE_RATE=$($Row.industry_coverage_rate)"
    Write-Host "THEME_COVERAGE_RATE=$($Row.theme_coverage_rate)"
    exit 0
}
finally { Pop-Location }
