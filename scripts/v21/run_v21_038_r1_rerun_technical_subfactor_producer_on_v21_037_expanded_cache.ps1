$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_038_r1_rerun_technical_subfactor_producer_on_v21_037_expanded_cache.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_038_R1_TECHNICAL_SUBFACTOR_RERUN_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.038-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.038-R1_RERUN_TECHNICAL_SUBFACTOR_PRODUCER_ON_V21_037_EXPANDED_CACHE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "input_cache_exists=$($SummaryRow.input_cache_exists)"
Write-Output "input_rows=$($SummaryRow.input_rows)"
Write-Output "excluded_pseudo_ticker_count=$($SummaryRow.excluded_pseudo_ticker_count)"
Write-Output "excluded_no_price_ticker_count=$($SummaryRow.excluded_no_price_ticker_count)"
Write-Output "total_subfactor_rows_produced=$($SummaryRow.total_subfactor_rows_produced)"
Write-Output "technical_score_coverage_ratio=$($SummaryRow.technical_score_coverage_ratio)"
Write-Output "row_quality_pass_ratio=$($SummaryRow.row_quality_pass_ratio)"
Write-Output "true_subfactor_capture_ready=$($SummaryRow.true_subfactor_capture_ready)"
Write-Output "true_reweighting_ready=$($SummaryRow.true_reweighting_ready)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
