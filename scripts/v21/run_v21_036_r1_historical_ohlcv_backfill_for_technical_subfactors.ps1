$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_036_r1_historical_ohlcv_backfill_for_technical_subfactors.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_036_R1_HISTORICAL_OHLCV_BACKFILL_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.036-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.036-R1_HISTORICAL_OHLCV_BACKFILL_FOR_TECHNICAL_SUBFACTORS"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "local_ohlcv_source_found=$($SummaryRow.local_ohlcv_source_found)"
Write-Output "total_normalized_rows_produced=$($SummaryRow.total_normalized_rows_produced)"
Write-Output "median_history_depth_by_ticker=$($SummaryRow.median_history_depth_by_ticker)"
Write-Output "technical_indicator_warmup_ready=$($SummaryRow.technical_indicator_warmup_ready)"
Write-Output "true_reweighting_ready=$($SummaryRow.true_reweighting_ready)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_mutation_allowed=$($SummaryRow.official_weight_mutation_allowed)"
