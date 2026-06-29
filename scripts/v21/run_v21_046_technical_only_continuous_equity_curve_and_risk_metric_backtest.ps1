$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_046_technical_only_continuous_equity_curve_and_risk_metric_backtest.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_046_EQUITY_CURVE_BACKTEST_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_best_variant_by_sharpe={0}" -f $Summary.best_variant_by_sharpe)
Write-Output ("wrapper_best_variant_by_total_return={0}" -f $Summary.best_variant_by_total_return)
Write-Output ("wrapper_QQQ_comparison_summary={0}" -f $Summary.QQQ_comparison_summary)
Write-Output ("wrapper_ETF_rotation_comparator_status={0}" -f $Summary.ETF_rotation_comparator_status)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
