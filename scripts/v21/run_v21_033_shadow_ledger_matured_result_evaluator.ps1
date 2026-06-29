$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_033_shadow_ledger_matured_result_evaluator.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Decision = Join-Path $Root "outputs\v21\shadow_observation\V21_033_SHADOW_EVALUATOR_DECISION.csv"

python $Runner | Out-Host

if (-not (Test-Path $Decision)) {
    throw "V21.033 decision output not found: $Decision"
}

$DecisionRow = Import-Csv $Decision | Select-Object -First 1
Write-Output "STAGE_NAME=V21_033_SHADOW_LEDGER_MATURED_RESULT_EVALUATOR"
Write-Output "final_status=$($DecisionRow.final_status)"
Write-Output "evaluator_decision=$($DecisionRow.evaluator_decision)"
Write-Output "recommended_next_stage=$($DecisionRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($DecisionRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($DecisionRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($DecisionRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($DecisionRow.official_weight_update_blocked)"
Write-Output "broker_execution_supported=$($DecisionRow.broker_execution_supported)"
Write-Output "shadow_activation=$($DecisionRow.shadow_activation)"
Write-Output "research_only=$($DecisionRow.research_only)"
