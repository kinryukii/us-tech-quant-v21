$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r8a_technical_only_ledger_maturity_wait_status.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_044_R8A_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_observation_as_of_date={0}" -f $Summary.observation_as_of_date)
Write-Output ("wrapper_max_ticker_price_date={0}" -f $Summary.max_ticker_price_date)
Write-Output ("wrapper_max_benchmark_price_date={0}" -f $Summary.max_benchmark_price_date)
Write-Output ("wrapper_rows_maturable_now={0}" -f $Summary.rows_maturable_now)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
