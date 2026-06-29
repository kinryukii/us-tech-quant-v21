$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_001_baseline_strategy_performance_audit.py"
$Gate = Join-Path (Split-Path -Parent (Split-Path -Parent $ScriptDir)) "outputs\v21\audit\V21_001_NEXT_STAGE_GATE.csv"

python $Runner | Out-Host

if (-not (Test-Path $Gate)) {
    throw "Gate output not found: $Gate"
}

$GateRow = Import-Csv $Gate | Select-Object -First 1
Write-Output "STAGE_NAME=V21_001_BASELINE_STRATEGY_PERFORMANCE_AUDIT"
Write-Output "final_status=$($GateRow.final_status)"
Write-Output "evaluated_forward_rows=$($GateRow.evaluated_forward_rows)"
Write-Output "evaluated_as_of_date_count=$($GateRow.evaluated_as_of_date_count)"
Write-Output "next_recommended_action=$($GateRow.next_recommended_action)"
