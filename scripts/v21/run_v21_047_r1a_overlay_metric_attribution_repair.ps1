Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r1a_overlay_metric_attribution_repair.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R1A Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R1A_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("repaired_best_balanced_overlay={0}" -f $Decision.repaired_best_balanced_overlay)
Write-Host ("TURNOVER_BUFFER_RANK_30_no_op_status={0}" -f $Decision.TURNOVER_BUFFER_RANK_30_no_op_status)
Write-Host ("any_single_overlay_review_worthy={0}" -f $Decision.any_single_overlay_review_worthy)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
