Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r3a_holdings_evidence_repair_for_primary_overlay.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R3A Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R3A_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("caveat_resolution={0}" -f $Decision.caveat_resolution)
Write-Host ("turnover_explanation={0}" -f $Decision.turnover_explanation)
Write-Host ("rank_buffer_evidence_status={0}" -f $Decision.rank_buffer_evidence_status)
Write-Host ("metric_reconciliation_status={0}" -f $Decision.metric_reconciliation_status)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
Write-Host ("overlay_adoption_allowed={0}" -f $Decision.overlay_adoption_allowed)
Write-Host ("official_adoption_allowed={0}" -f $Decision.official_adoption_allowed)
Write-Host ("shadow_gate_allowed={0}" -f $Decision.shadow_gate_allowed)
