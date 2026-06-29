$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_016_risk_regime_gate_and_modifier_research_prototype.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\factor_backtest\V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE_SUMMARY.csv"
python $Runner | Out-Host
if (-not (Test-Path $Summary)) { throw "V21.016 summary output not found: $Summary" }
$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_016_RISK_REGIME_GATE_AND_MODIFIER_RESEARCH_PROTOTYPE"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "risk_regime_decision=$($SummaryRow.risk_regime_decision)"
Write-Output "selected_variant=$($SummaryRow.selected_variant)"
Write-Output "v21_020_confirmation_decision=$($SummaryRow.v21_020_confirmation_decision)"
Write-Output "v21_020_selected_variant=$($SummaryRow.v21_020_selected_variant)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($SummaryRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($SummaryRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "data_trust_ranking_weight=$($SummaryRow.data_trust_ranking_weight)"
Write-Output "data_trust_alpha_contribution=$($SummaryRow.data_trust_alpha_contribution)"
Write-Output "official_ranking_mutation_count=$($SummaryRow.official_ranking_mutation_count)"
Write-Output "official_factor_weight_mutation_count=$($SummaryRow.official_factor_weight_mutation_count)"
Write-Output "official_recommendation_count=$($SummaryRow.official_recommendation_count)"
Write-Output "trade_action_count=$($SummaryRow.trade_action_count)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
