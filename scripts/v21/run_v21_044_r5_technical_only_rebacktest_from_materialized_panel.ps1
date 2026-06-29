$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r5_technical_only_rebacktest_from_materialized_panel.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\backtest\V21_044_R5_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
$Excess = "5D={0}|10D={1}|20D={2}|60D={3}" -f $Summary.top20_excess_vs_QQQ_5D, $Summary.top20_excess_vs_QQQ_10D, $Summary.top20_excess_vs_QQQ_20D, $Summary.top20_excess_vs_QQQ_60D
Write-Output ("final_status={0}" -f $Summary.final_status)
Write-Output ("decision={0}" -f $Summary.decision)
Write-Output ("sampled_asof_count={0}" -f $Summary.sampled_asof_count)
Write-Output ("qqq_excess_summary={0}" -f $Excess)
Write-Output ("reproduction_status={0}" -f $Summary.reproduction_status_summary)
