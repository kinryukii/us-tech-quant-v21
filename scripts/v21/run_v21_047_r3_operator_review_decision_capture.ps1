Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

python scripts/v21/v21_047_r3_operator_review_decision_capture.py
if ($LASTEXITCODE -ne 0) {
    throw "V21.047-R3 Python stage failed with exit code $LASTEXITCODE"
}

$DecisionPath = "outputs/v21/review/V21_047_R3_DECISION_SUMMARY.csv"
if (-not (Test-Path $DecisionPath)) {
    throw "Decision summary not found: $DecisionPath"
}

$Decision = Import-Csv $DecisionPath | Select-Object -First 1
Write-Host ("final_status={0}" -f $Decision.final_status)
Write-Host ("decision={0}" -f $Decision.decision)
Write-Host ("primary_candidate={0}" -f $Decision.primary_candidate)
Write-Host ("operator_input_source={0}" -f $Decision.operator_input_source)
Write-Host ("recommended_next_stage={0}" -f $Decision.recommended_next_stage)
Write-Host ("overlay_adoption_allowed={0}" -f $Decision.overlay_adoption_allowed)
Write-Host ("official_adoption_allowed={0}" -f $Decision.official_adoption_allowed)
Write-Host ("shadow_gate_allowed={0}" -f $Decision.shadow_gate_allowed)
