$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r8a_wait_until_first_maturity_date.py"
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
Write-Output ("wrapper_first_maturity_date={0}" -f $Summary.first_maturity_date)
Write-Output ("wrapper_r9_allowed_now={0}" -f $Summary.r9_allowed_now)
Write-Output ("wrapper_r8_rerun_condition={0}" -f $Summary.r8_rerun_condition)
Write-Output ("wrapper_full_weight_blocked={0}" -f $Summary.full_weight_blocked)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
