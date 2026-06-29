$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_029_r1_current_daily_shadow_observation_rebuilder.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\shadow_observation\V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.029-R1 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_029_R1_CURRENT_DAILY_SHADOW_OBSERVATION_REBUILDER"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "rebuilder_decision=$($SummaryRow.rebuilder_decision)"
Write-Output "source_repaired_label_date=$($SummaryRow.source_repaired_label_date)"
Write-Output "ledger_row_count=$($SummaryRow.ledger_row_count)"
Write-Output "fallback_used=$($SummaryRow.fallback_used)"
Write-Output "current_daily_observation_allowed=$($SummaryRow.current_daily_observation_allowed)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($SummaryRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($SummaryRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "broker_execution_supported=$($SummaryRow.broker_execution_supported)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
