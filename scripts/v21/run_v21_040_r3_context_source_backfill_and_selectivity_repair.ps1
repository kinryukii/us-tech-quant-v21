$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_040_r3_context_source_backfill_and_selectivity_repair.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_040_R3_CONTEXT_SELECTIVITY_REPAIR_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.040-R3 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.040-R3_CONTEXT_SOURCE_BACKFILL_AND_SELECTIVITY_REPAIR"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "r2_canonical_ledger_rows=$($SummaryRow.r2_canonical_ledger_rows)"
Write-Output "r3_ledger_rows=$($SummaryRow.r3_ledger_rows)"
Write-Output "overbroadcast_context_count_before=$($SummaryRow.overbroadcast_context_count_before)"
Write-Output "overbroadcast_context_count_after=$($SummaryRow.overbroadcast_context_count_after)"
Write-Output "missing_context_before_count=$($SummaryRow.missing_context_before_count)"
Write-Output "missing_context_after_count=$($SummaryRow.missing_context_after_count)"
Write-Output "missing_context_reduction_ratio=$($SummaryRow.missing_context_reduction_ratio)"
Write-Output "context_source_file_count_scanned=$($SummaryRow.context_source_file_count_scanned)"
Write-Output "context_source_file_count_usable=$($SummaryRow.context_source_file_count_usable)"
Write-Output "context_overbroadcast_after=$($SummaryRow.context_overbroadcast_after)"
Write-Output "context_selectivity_ready_after=$($SummaryRow.context_selectivity_ready_after)"
Write-Output "technical_reweighting_retest_allowed=$($SummaryRow.technical_reweighting_retest_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
