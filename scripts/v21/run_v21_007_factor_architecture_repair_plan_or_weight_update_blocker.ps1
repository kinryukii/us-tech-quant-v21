$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_007_factor_architecture_repair_plan_or_weight_update_blocker.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.007 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_007_FACTOR_ARCHITECTURE_REPAIR_PLAN_OR_WEIGHT_UPDATE_BLOCKER"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "v21_006_final_status=$($SummaryRow.v21_006_final_status)"
Write-Output "v21_006_final_verdict=$($SummaryRow.v21_006_final_verdict)"
Write-Output "weight_update_blocker_decision=$($SummaryRow.weight_update_blocker_decision)"
Write-Output "outlier_dependency_classification=$($SummaryRow.outlier_dependency_classification)"
Write-Output "regime_dependency_classification=$($SummaryRow.regime_dependency_classification)"
Write-Output "risk_overheat_repair_classification=$($SummaryRow.risk_overheat_repair_classification)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
