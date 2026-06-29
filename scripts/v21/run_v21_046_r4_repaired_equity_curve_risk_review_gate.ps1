$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_046_r4_repaired_equity_curve_risk_review_gate.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_046_R4_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_best_repaired_variant={0}" -f $Summary.best_repaired_variant)
Write-Output ("wrapper_drawdown_status={0}" -f $Summary.drawdown_status)
Write-Output ("wrapper_turnover_status={0}" -f $Summary.turnover_status)
Write-Output ("wrapper_stability_status={0}" -f $Summary.stability_status)
Write-Output ("wrapper_ETF_comparator_status={0}" -f $Summary.ETF_comparator_limitation_status)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
