$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_041_r1_technical_reweighting_retest_with_r4_context_buckets_research_only.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_041_R1_TECHNICAL_REWEIGHTING_RETEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.041-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.041-R1_TECHNICAL_REWEIGHTING_RETEST_WITH_R4_CONTEXT_BUCKETS_RESEARCH_ONLY"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "r4_retest_allowed=$($SummaryRow.r4_retest_allowed)"
Write-Output "variants_tested_count=$($SummaryRow.variants_tested_count)"
Write-Output "eligible_context_bucket_count=$($SummaryRow.eligible_context_bucket_count)"
Write-Output "matured_rows_used=$($SummaryRow.matured_rows_used)"
Write-Output "best_research_variant_name=$($SummaryRow.best_research_variant_name)"
Write-Output "best_research_variant_selected=$($SummaryRow.best_research_variant_selected)"
Write-Output "best_variant_mean_excess_vs_baseline=$($SummaryRow.best_variant_mean_excess_vs_baseline)"
Write-Output "shadow_gate_candidate_recommended=$($SummaryRow.shadow_gate_candidate_recommended)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
