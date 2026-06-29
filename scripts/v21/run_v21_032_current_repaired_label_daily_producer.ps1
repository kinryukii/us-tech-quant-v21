$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v21_032_current_repaired_label_daily_producer.py"
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Summary = Join-Path $Root "outputs\v21\shadow_observation\V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER_SUMMARY.csv"

python $Runner | Out-Host

if (-not (Test-Path $Summary)) {
    throw "V21.032 summary output not found: $Summary"
}

$SummaryRow = Import-Csv $Summary | Select-Object -First 1
Write-Output "STAGE_NAME=V21_032_CURRENT_REPAIRED_LABEL_DAILY_PRODUCER"
Write-Output "final_status=$($SummaryRow.final_status)"
Write-Output "producer_decision=$($SummaryRow.producer_decision)"
Write-Output "latest_available_current_daily_candidate_date=$($SummaryRow.latest_available_current_daily_candidate_date)"
Write-Output "previous_repaired_label_latest_date=$($SummaryRow.previous_repaired_label_latest_date)"
Write-Output "produced_repaired_label_date=$($SummaryRow.produced_repaired_label_date)"
Write-Output "fallback_required_after=$($SummaryRow.fallback_required_after)"
Write-Output "current_daily_observation_allowed_after=$($SummaryRow.current_daily_observation_allowed_after)"
Write-Output "recommended_next_stage=$($SummaryRow.recommended_next_stage)"
Write-Output "official_use_allowed=$($SummaryRow.official_use_allowed)"
Write-Output "official_ranking_readiness_allowed=$($SummaryRow.official_ranking_readiness_allowed)"
Write-Output "official_weight_update_readiness_allowed=$($SummaryRow.official_weight_update_readiness_allowed)"
Write-Output "official_weight_update_blocked=$($SummaryRow.official_weight_update_blocked)"
Write-Output "broker_execution_supported=$($SummaryRow.broker_execution_supported)"
Write-Output "shadow_activation=$($SummaryRow.shadow_activation)"
Write-Output "research_only=$($SummaryRow.research_only)"
