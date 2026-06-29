$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r4_full_family_historical_score_materializer_with_explicit_source_blocks.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_044_R4_MATERIALIZATION_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("final_status={0}" -f $Summary.final_status)
Write-Output ("decision={0}" -f $Summary.decision)
Write-Output ("technical_materialized_row_count={0}" -f $Summary.technical_materialized_row_count)
Write-Output ("blocked_family_count={0}" -f $Summary.blocked_family_count)
Write-Output ("technical_only_backtest_allowed_next={0}" -f $Summary.technical_only_backtest_allowed_next)
