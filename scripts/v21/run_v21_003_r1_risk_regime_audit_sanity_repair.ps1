$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_003_r1_risk_regime_audit_sanity_repair.py"
$Gate = Join-Path (Split-Path -Parent (Split-Path -Parent $ScriptDir)) "outputs\v21\recalibration_r1\V21_003_R1_NEXT_STAGE_GATE.csv"

python $Runner | Out-Host

if (-not (Test-Path $Gate)) {
    throw "Gate output not found: $Gate"
}

$GateRow = Import-Csv $Gate | Select-Object -First 1
Write-Output "STAGE_NAME=V21_003_R1_RISK_REGIME_AUDIT_SANITY_REPAIR"
Write-Output "final_status=$($GateRow.final_status)"
Write-Output "original_overheat_false_block_candidate_count=$($GateRow.original_overheat_false_block_candidate_count)"
Write-Output "repaired_true_overheat_row_count=$($GateRow.repaired_true_overheat_row_count)"
Write-Output "repaired_false_block_candidate_count=$($GateRow.repaired_false_block_candidate_count)"
Write-Output "removed_not_overheat_row_count=$($GateRow.removed_not_overheat_row_count)"
Write-Output "contamination_ratio=$($GateRow.contamination_ratio)"
Write-Output "risk_score_direction_audited_field_count=$($GateRow.risk_score_direction_audited_field_count)"
Write-Output "regime_score_direction_audited_field_count=$($GateRow.regime_score_direction_audited_field_count)"
Write-Output "next_recommended_action=$($GateRow.next_recommended_action)"
