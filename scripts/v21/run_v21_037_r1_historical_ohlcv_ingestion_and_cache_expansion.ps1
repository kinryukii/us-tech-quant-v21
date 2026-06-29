$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_037_r1_historical_ohlcv_ingestion_and_cache_expansion.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_037_R1_HISTORICAL_OHLCV_INGESTION_SUMMARY.csv"

$ArgsToPass = @()
if ($env:V21_ALLOW_NETWORK_BACKFILL -eq "TRUE") {
    $ArgsToPass += "--allow-network-backfill"
}

python $Runner @ArgsToPass | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.037-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.037-R1_HISTORICAL_OHLCV_INGESTION_AND_CACHE_EXPANSION"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "ingestion_mode=$($SummaryRow.ingestion_mode)"
Write-Output "local_source_found=$($SummaryRow.local_source_found)"
Write-Output "network_backfill_enabled=$($SummaryRow.network_backfill_enabled)"
Write-Output "network_backfill_used=$($SummaryRow.network_backfill_used)"
Write-Output "total_rows_after_ingestion=$($SummaryRow.total_rows_after_ingestion)"
Write-Output "median_history_depth_by_ticker_after_ingestion=$($SummaryRow.median_history_depth_by_ticker_after_ingestion)"
Write-Output "technical_indicator_warmup_ready=$($SummaryRow.technical_indicator_warmup_ready)"
Write-Output "true_reweighting_ready=$($SummaryRow.true_reweighting_ready)"
Write-Output "research_only=$($SummaryRow.research_only)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
