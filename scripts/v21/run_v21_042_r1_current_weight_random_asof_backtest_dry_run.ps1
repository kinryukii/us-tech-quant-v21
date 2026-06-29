$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_042_r1_current_weight_random_asof_backtest_dry_run.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\backtest\V21_042_R1_RANDOM_ASOF_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("final_status={0}" -f $Summary.final_status)
Write-Output ("decision={0}" -f $Summary.decision)
Write-Output ("current_weight_source={0}" -f $Summary.current_weight_source)
Write-Output ("sampled_asof_count={0}" -f $Summary.sampled_asof_count)

