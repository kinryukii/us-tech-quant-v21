$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_041_r3_maturity_refresh_or_keep_baseline_review.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_041_R3_MATURITY_REFRESH_OR_KEEP_BASELINE_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.041-R3 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.041-R3_MATURITY_REFRESH_OR_KEEP_BASELINE_REVIEW"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "current_research_stance=$($SummaryRow.current_research_stance)"
Write-Output "future_retest_allowed_after_maturity=$($SummaryRow.future_retest_allowed_after_maturity)"
Write-Output "context_conditioned_excess_vs_baseline=$($SummaryRow.context_conditioned_excess_vs_baseline)"
Write-Output "context_conditioned_excess_vs_global_rsi_deemphasized=$($SummaryRow.context_conditioned_excess_vs_global_rsi_deemphasized)"
Write-Output "edge_concentration_gate_pass=$($SummaryRow.edge_concentration_gate_pass)"
Write-Output "shadow_review_allowed_now=$($SummaryRow.shadow_review_allowed_now)"
Write-Output "shadow_dry_run_candidate_allowed=$($SummaryRow.shadow_dry_run_candidate_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
