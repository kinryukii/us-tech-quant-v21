Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r3c_primary_overlay_metric_reconciliation_repair.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R3C Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R3C_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("corrected_primary_candidate={0}" -f $Decision.corrected_primary_review_candidate)
Write-Host ("turnover_claim_repair_result={0}" -f $Decision.turnover_claim_repair_result)
Write-Host ("equivalence_status={0}" -f $Decision.combined_vs_QQQ_MA50_equivalence_status)
Write-Host ("cost_warning_status={0}" -f $Decision.cost_warning_recheck_result)
Write-Host ("review_continuation_status={0}" -f $Decision.review_can_continue)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
Write-Host ("overlay_adoption_allowed={0}" -f $Decision.overlay_adoption_allowed)
Write-Host ("official_adoption_allowed={0}" -f $Decision.official_adoption_allowed)
Write-Host ("shadow_gate_allowed={0}" -f $Decision.shadow_gate_allowed)
