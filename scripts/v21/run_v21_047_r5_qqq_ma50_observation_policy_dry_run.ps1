Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r5_qqq_ma50_observation_policy_dry_run.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R5 Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R5_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}
$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("corrected_primary_candidate={0}" -f $Decision.corrected_primary_overlay)
Write-Host ("latest_QQQ_date={0}" -f $Decision.latest_QQQ_date)
Write-Host ("QQQ_MA50_state={0}" -f $Decision.QQQ_MA50_state)
Write-Host ("dry_run_target_exposure={0}" -f $Decision.dry_run_target_exposure)
Write-Host ("ledger_append_status={0}" -f $Decision.ledger_append_status)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
Write-Host ("overlay_adoption_allowed={0}" -f $Decision.overlay_adoption_allowed)
Write-Host ("official_adoption_allowed={0}" -f $Decision.official_adoption_allowed)
Write-Host ("shadow_gate_allowed={0}" -f $Decision.shadow_gate_allowed)
