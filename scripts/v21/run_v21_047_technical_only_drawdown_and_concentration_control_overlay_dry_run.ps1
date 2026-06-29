$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_047_technical_only_drawdown_and_concentration_control_overlay_dry_run.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_047_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_best_overlay={0}" -f $Summary.best_balanced_overlay)
Write-Output ("wrapper_turnover_reduction={0}" -f $Summary.turnover_reduction)
Write-Output ("wrapper_drawdown_improvement={0}" -f $Summary.drawdown_improvement)
Write-Output ("wrapper_Sharpe_preservation={0}" -f $Summary.Sharpe_preservation)
Write-Output ("wrapper_total_return_preservation={0}" -f $Summary.total_return_preservation)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
