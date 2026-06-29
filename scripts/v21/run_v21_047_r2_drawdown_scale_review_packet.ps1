Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r2_drawdown_scale_review_packet.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R2 Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R2_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("surviving_review_only_candidates={0}" -f $Decision.surviving_review_only_candidates)
Write-Host ("rejected_no_op_overlays={0}" -f $Decision.rejected_no_op_overlays)
Write-Host ("alpha_preservation_status={0}" -f $Decision.alpha_preservation_status)
Write-Host ("turnover_cost_status={0}" -f $Decision.turnover_cost_status)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
