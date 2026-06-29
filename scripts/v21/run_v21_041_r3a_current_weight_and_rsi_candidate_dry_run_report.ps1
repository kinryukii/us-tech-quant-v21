$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_041_r3a_current_weight_and_rsi_candidate_dry_run_report.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factors\V21_041_R3A_CURRENT_WEIGHT_DRY_RUN_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.041-R3A summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21.041-R3A_CURRENT_WEIGHT_AND_RSI_CANDIDATE_DRY_RUN_REPORT"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "decision=$($SummaryRow.decision)"
Write-Output "current_input_rows=$($SummaryRow.current_input_rows)"
Write-Output "current_distinct_tickers=$($SummaryRow.current_distinct_tickers)"
Write-Output "top20_overlap_baseline_vs_global_rsi=$($SummaryRow.top20_overlap_baseline_vs_global_rsi)"
Write-Output "top20_overlap_baseline_vs_context_conditioned=$($SummaryRow.top20_overlap_baseline_vs_context_conditioned)"
Write-Output "top40_overlap_baseline_vs_global_rsi=$($SummaryRow.top40_overlap_baseline_vs_global_rsi)"
Write-Output "top40_overlap_baseline_vs_context_conditioned=$($SummaryRow.top40_overlap_baseline_vs_context_conditioned)"
Write-Output "official_adoption_allowed=$($SummaryRow.official_adoption_allowed)"
Write-Output "shadow_gate_allowed=$($SummaryRow.shadow_gate_allowed)"
Write-Output "research_only=$($SummaryRow.research_only)"
