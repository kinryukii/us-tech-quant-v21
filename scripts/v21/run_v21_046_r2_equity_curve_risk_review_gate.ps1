$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_046_r2_equity_curve_risk_review_gate.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_046_R2_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_best_v21_046_curve={0}" -f $Summary.best_v21_046_curve)
Write-Output ("wrapper_extreme_performance_warning={0}" -f $Summary.extreme_performance_warning)
Write-Output ("wrapper_return_construction_status={0}" -f $Summary.return_construction_status)
Write-Output ("wrapper_price_outlier_status={0}" -f $Summary.price_outlier_status)
Write-Output ("wrapper_concentration_status={0}" -f $Summary.concentration_status)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
