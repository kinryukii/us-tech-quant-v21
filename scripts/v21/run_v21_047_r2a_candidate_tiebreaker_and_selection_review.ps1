Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r2a_candidate_tiebreaker_and_selection_review.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R2A Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R2A_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("primary_review_candidate={0}" -f $Decision.primary_review_candidate)
Write-Host ("secondary_review_candidate={0}" -f $Decision.secondary_review_candidate)
Write-Host ("cost_warning_status={0}" -f $Decision.cost_warning_status)
Write-Host ("downside_monitor_dependency={0}" -f $Decision.downside_monitor_dependency)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
