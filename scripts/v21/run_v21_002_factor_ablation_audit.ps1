$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_002_factor_ablation_audit.py"
$Gate = Join-Path (Split-Path -Parent (Split-Path -Parent $ScriptDir)) "outputs\v21\ablation\V21_002_NEXT_STAGE_GATE.csv"

python $Runner | Out-Host

if (-not (Test-Path $Gate)) {
    throw "Gate output not found: $Gate"
}

$GateRow = Import-Csv $Gate | Select-Object -First 1
Write-Output "STAGE_NAME=V21_002_FACTOR_ABLATION_AUDIT"
Write-Output "final_status=$($GateRow.final_status)"
Write-Output "joined_factor_outcome_rows=$($GateRow.joined_factor_outcome_rows)"
Write-Output "evaluated_factor_family_count=$($GateRow.evaluated_factor_family_count)"
Write-Output "negative_contributor_count=$($GateRow.negative_contributor_count)"
Write-Output "positive_contributor_count=$($GateRow.positive_contributor_count)"
Write-Output "next_recommended_action=$($GateRow.next_recommended_action)"
