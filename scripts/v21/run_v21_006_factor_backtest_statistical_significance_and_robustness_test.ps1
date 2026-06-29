$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_006_factor_backtest_statistical_significance_and_robustness_test.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_006_BACKTEST_STATISTICAL_TEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.006 statistical test summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_006_FACTOR_BACKTEST_STATISTICAL_SIGNIFICANCE_AND_ROBUSTNESS_TEST"
Write-Output "final_verdict=$($SummaryRow.final_verdict)"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "usable_primary_matured_observation_count=$($SummaryRow.usable_primary_matured_observation_count)"
Write-Output "rejected_or_diagnostic_observation_count=$($SummaryRow.rejected_or_diagnostic_observation_count)"
Write-Output "distinct_as_of_dates=$($SummaryRow.distinct_as_of_dates)"
Write-Output "distinct_tickers=$($SummaryRow.distinct_tickers)"
Write-Output "evaluated_forward_windows=$($SummaryRow.evaluated_forward_windows)"
Write-Output "random_trial_count=$($SummaryRow.random_trial_count)"
Write-Output "random_seed_base=$($SummaryRow.random_seed_base)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "research_only=$($SummaryRow.research_only)"
