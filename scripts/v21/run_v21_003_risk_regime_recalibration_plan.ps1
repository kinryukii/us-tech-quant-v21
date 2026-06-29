$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_003_risk_regime_recalibration_plan.py"
$Gate = Join-Path (Split-Path -Parent (Split-Path -Parent $ScriptDir)) "outputs\v21\recalibration\V21_003_NEXT_STAGE_GATE.csv"

python $Runner | Out-Host

if (-not (Test-Path $Gate)) {
    throw "Gate output not found: $Gate"
}

$GateRow = Import-Csv $Gate | Select-Object -First 1
Write-Output "STAGE_NAME=V21_003_RISK_REGIME_RECALIBRATION_PLAN"
Write-Output "final_status=$($GateRow.final_status)"
Write-Output "joined_risk_regime_outcome_rows=$($GateRow.joined_risk_regime_outcome_rows)"
Write-Output "evaluated_regime_segment_count=$($GateRow.evaluated_regime_segment_count)"
Write-Output "evaluated_risk_score_field_count=$($GateRow.evaluated_risk_score_field_count)"
Write-Output "overheat_false_block_candidate_count=$($GateRow.overheat_false_block_candidate_count)"
Write-Output "risk_overpenalization_candidate_count=$($GateRow.risk_overpenalization_candidate_count)"
Write-Output "regime_misalignment_candidate_count=$($GateRow.regime_misalignment_candidate_count)"
Write-Output "recalibration_scenario_count=$($GateRow.recalibration_scenario_count)"
Write-Output "next_recommended_action=$($GateRow.next_recommended_action)"
