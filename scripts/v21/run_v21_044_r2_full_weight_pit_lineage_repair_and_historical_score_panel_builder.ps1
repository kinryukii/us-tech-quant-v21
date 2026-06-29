$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

$PythonScript = Join-Path $ScriptDir "v21_044_r2_full_weight_pit_lineage_repair_and_historical_score_panel_builder.py"
if (-not (Test-Path $PythonScript)) {
    throw "Missing Python stage: $PythonScript"
}

python $PythonScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$SummaryPath = Join-Path $RepoRoot "outputs\v21\review\V21_044_R2_FULL_WEIGHT_PANEL_DECISION_SUMMARY.csv"
if (-not (Test-Path $SummaryPath)) {
    throw "Decision summary was not created: $SummaryPath"
}

$Summary = Import-Csv $SummaryPath | Select-Object -First 1
Write-Output ("final_status={0}" -f $Summary.final_status)
Write-Output ("decision={0}" -f $Summary.decision)
Write-Output ("pit_safe_row_count={0}" -f $Summary.pit_safe_row_count)
Write-Output ("built_panel_row_count={0}" -f $Summary.historical_panel_row_count)
Write-Output ("eligible_asof_count={0}" -f $Summary.eligible_asof_count)
