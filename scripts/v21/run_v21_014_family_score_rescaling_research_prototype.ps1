$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_014_family_score_rescaling_research_prototype.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.014 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_014_FAMILY_SCORE_RESCALING_RESEARCH_PROTOTYPE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "rescaling_prototype_decision=$($SummaryRow.rescaling_prototype_decision)"
Write-Output "selected_variant=$($SummaryRow.selected_variant)"
Write-Output "v21_011_architecture_repair_decision=$($SummaryRow.v21_011_architecture_repair_decision)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "research_only_limited_weight_experiment_allowed=$($SummaryRow.research_only_limited_weight_experiment_allowed)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "evaluated_variant_count=$($SummaryRow.evaluated_variant_count)"
Write-Output "prototype_score_output_path=$($SummaryRow.prototype_score_output_path)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
