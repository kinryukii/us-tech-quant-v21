$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_039_r1_true_technical_subfactor_reweighting_backtest_research_only.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_039_R1_TRUE_TECHNICAL_REWEIGHTING_BACKTEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.039-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.039-R1_TRUE_TECHNICAL_SUBFACTOR_REWEIGHTING_BACKTEST_RESEARCH_ONLY"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "matured_forward_return_source_found=$($SummaryRow.matured_forward_return_source_found)"
Write-Output "matured_rows_used=$($SummaryRow.matured_rows_used)"
Write-Output "immature_rows_excluded=$($SummaryRow.immature_rows_excluded)"
Write-Output "variants_tested_count=$($SummaryRow.variants_tested_count)"
Write-Output "best_research_variant_name=$($SummaryRow.best_research_variant_name)"
Write-Output "best_research_variant_selected=$($SummaryRow.best_research_variant_selected)"
Write-Output "best_variant_mean_excess_vs_baseline=$($SummaryRow.best_variant_mean_excess_vs_baseline)"
Write-Output "true_technical_reweighting_ready_for_shadow_gate=$($SummaryRow.true_technical_reweighting_ready_for_shadow_gate)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
