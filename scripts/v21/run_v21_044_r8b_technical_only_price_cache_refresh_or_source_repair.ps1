$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r8b_technical_only_price_cache_refresh_or_source_repair.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_044_R8B_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("wrapper_final_status={0}" -f $Summary.final_status)
Write-Output ("wrapper_decision={0}" -f $Summary.decision)
Write-Output ("wrapper_local_source_covers_2026_06_16={0}" -f $Summary.local_source_covers_2026_06_16)
Write-Output ("wrapper_selected_repair_source={0}" -f $Summary.selected_repair_source)
Write-Output ("wrapper_r8_rerun_allowed_now={0}" -f $Summary.r8_rerun_allowed_now)
Write-Output ("wrapper_recommended_next_stage={0}" -f $Summary.recommended_next_stage)
