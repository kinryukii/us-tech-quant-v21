param(
    [string]$InputLedger,
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$argsList = @("scripts/v21/v21_184_dram_intraday_outcome_dashboard_and_decision_summary.py")
if ($InputLedger) {
    $argsList += @("--input-ledger", $InputLedger)
}
if ($OutputDir) {
    $argsList += @("--output-dir", $OutputDir)
}

python @argsList
$code = $LASTEXITCODE

$summaryPath = if ($OutputDir) {
    Join-Path $OutputDir "v21_184_summary.json"
} else {
    "outputs/v21/V21.184_DRAM_INTRADAY_OUTCOME_DASHBOARD_AND_DECISION_SUMMARY/v21_184_summary.json"
}

if (Test-Path $summaryPath) {
    $summary = Get-Content $summaryPath -Raw | ConvertFrom-Json
    Write-Host ("FINAL_STATUS=" + $summary.final_status)
    Write-Host ("OUTPUT_DIR=" + (Split-Path $summaryPath -Parent))
}

exit $code
