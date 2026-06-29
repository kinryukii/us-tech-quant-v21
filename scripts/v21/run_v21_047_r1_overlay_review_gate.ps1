Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r1_overlay_review_gate.py

$DecisionPath = "outputs/v21/review/V21_047_R1_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("best_balanced_overlay={0}" -f $Decision.best_balanced_overlay)
Write-Host ("metric_attribution_status={0}" -f $Decision.metric_attribution_status)
Write-Host ("turnover_status={0}" -f $Decision.turnover_overlay_review_result)
Write-Host ("drawdown_status={0}" -f $Decision.drawdown_overlay_review_result)
Write-Host ("cost_status={0}" -f $Decision.cost_aware_review_result)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
