$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_040_r2_forward_context_repair_and_maturity_refresh.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_040_R2_FORWARD_CONTEXT_REPAIR_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.040-R2 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.040-R2_FORWARD_CONTEXT_REPAIR_AND_MATURITY_REFRESH"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "canonical_forward_ledger_created=$($SummaryRow.canonical_forward_ledger_created)"
Write-Output "canonical_forward_ledger_rows=$($SummaryRow.canonical_forward_ledger_rows)"
Write-Output "source_count_used=$($SummaryRow.source_count_used)"
Write-Output "missing_context_before_count=$($SummaryRow.missing_context_before_count)"
Write-Output "missing_context_after_count=$($SummaryRow.missing_context_after_count)"
Write-Output "missing_context_reduction_ratio=$($SummaryRow.missing_context_reduction_ratio)"
Write-Output "context_overbroadcast_after=$($SummaryRow.context_overbroadcast_after)"
Write-Output "context_selectivity_ready_after=$($SummaryRow.context_selectivity_ready_after)"
Write-Output "technical_reweighting_retest_allowed=$($SummaryRow.technical_reweighting_retest_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
