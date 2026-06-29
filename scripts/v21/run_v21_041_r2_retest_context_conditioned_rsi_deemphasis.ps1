$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_041_r2_retest_context_conditioned_rsi_deemphasis.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_041_R2_CONTEXT_CONDITIONED_RETEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.041-R2 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.041-R2_RETEST_CONTEXT_CONDITIONED_RSI_DEEMPHASIS"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "context_conditioned_candidate_name=$($SummaryRow.context_conditioned_candidate_name)"
Write-Output "context_conditioned_excess_vs_baseline=$($SummaryRow.context_conditioned_excess_vs_baseline)"
Write-Output "context_conditioned_excess_vs_global_rsi_deemphasized=$($SummaryRow.context_conditioned_excess_vs_global_rsi_deemphasized)"
Write-Output "context_conditioned_candidate_selected=$($SummaryRow.context_conditioned_candidate_selected)"
Write-Output "shadow_review_candidate_recommended=$($SummaryRow.shadow_review_candidate_recommended)"
Write-Output "shadow_dry_run_candidate_allowed=$($SummaryRow.shadow_dry_run_candidate_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
