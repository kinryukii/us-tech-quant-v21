$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_011_factor_family_rescaling_and_nonlinear_interaction_test.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.011 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_011_FACTOR_FAMILY_RESCALING_AND_NONLINEAR_INTERACTION_TEST"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "architecture_repair_decision=$($SummaryRow.architecture_repair_decision)"
Write-Output "v21_008_regime_segmentation_decision=$($SummaryRow.v21_008_regime_segmentation_decision)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "research_only_limited_weight_experiment_allowed=$($SummaryRow.research_only_limited_weight_experiment_allowed)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
