$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r8_technical_only_ledger_maturity_refresh.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_044_R8_TECHNICAL_ONLY_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_input_ledger_row_count={0}" -f $Summary.input_ledger_row_count)
Write-Output ("wrapper_matured_row_count={0}" -f $Summary.matured_row_count)
Write-Output ("wrapper_pending_row_count={0}" -f $Summary.pending_row_count)
Write-Output ("wrapper_price_missing_row_count={0}" -f $Summary.price_missing_row_count)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
