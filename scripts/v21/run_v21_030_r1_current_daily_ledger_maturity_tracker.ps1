$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_030_r1_current_daily_ledger_maturity_tracker.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Decision = Join-Path $Root "outputs\v21\shadow_observation\V21_030_R1_CURRENT_DAILY_MATURITY_TRACKER_DECISION.csv"
$Integrity = Join-Path $Root "outputs\v21\shadow_observation\V21_030_R1_CURRENT_DAILY_LEDGER_INTEGRITY_AUDIT.csv"

python $Runner | Out-Host

if (-not (Test-Path $Decision)) {
    throw "V21.030-R1 decision output not found: $Decision"
}
if (-not (Test-Path $Integrity)) {
    throw "V21.030-R1 integrity output not found: $Integrity"
}

$DecisionRow = Import-Csv $Decision | Select-Object -First 1
$IntegrityRow = Import-Csv $Integrity | Select-Object -First 1

Write-Output "STAGE_NAME=V21_030_R1_CURRENT_DAILY_LEDGER_MATURITY_TRACKER"
Write-Output "final_status=$($DecisionRow.final_status)"
Write-Output "maturity_tracker_decision=$($DecisionRow.maturity_tracker_decision)"
Write-Output "source_ledger_as_of_date=$($DecisionRow.source_ledger_as_of_date)"
Write-Output "source_repaired_label_date=$($DecisionRow.source_repaired_label_date)"
Write-Output "row_count=$($IntegrityRow.row_count)"
Write-Output "pending_schedule_count=$($IntegrityRow.pending_schedule_count)"
Write-Output "fallback_used=$($DecisionRow.fallback_used)"
Write-Output "current_daily_observation_allowed=$($DecisionRow.current_daily_observation_allowed)"
Write-Output "recommended_next_stage=$($DecisionRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($DecisionRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($DecisionRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($DecisionRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($DecisionRow.official_weight_update_blocked)"
Write-Output "broker_execution_supported=$($DecisionRow.broker_execution_supported)"
Write-Output "shadow_activation=$($DecisionRow.shadow_activation)"
Write-Output "research_only=$($DecisionRow.research_only)"
