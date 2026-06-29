$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_020_rescaling_candidate_robustness_confirmation.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.020 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_020_RESCALING_CANDIDATE_ROBUSTNESS_CONFIRMATION"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "confirmation_decision=$($SummaryRow.confirmation_decision)"
Write-Output "selected_variant=$($SummaryRow.selected_variant)"
Write-Output "v21_014_rescaling_prototype_decision=$($SummaryRow.v21_014_rescaling_prototype_decision)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($SummaryRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($SummaryRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "research_only_limited_weight_experiment_allowed=$($SummaryRow.research_only_limited_weight_experiment_allowed)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "risk_additive_alpha_contribution=$($SummaryRow.risk_additive_alpha_contribution)"
Write-Output "market_regime_additive_alpha_contribution=$($SummaryRow.market_regime_additive_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
