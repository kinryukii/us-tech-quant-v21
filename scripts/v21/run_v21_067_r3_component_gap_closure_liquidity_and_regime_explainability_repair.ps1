Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_067_r3_component_gap_closure_liquidity_and_regime_explainability_repair.py"
$ValidationPath = Join-Path $RepoRoot "outputs\v21\explainability\V21_067_R3_VALIDATION_SUMMARY.csv"

Push-Location $RepoRoot
try {
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $ValidationPath)) {
        throw "V21.067-R3 validation summary was not created."
    }
    $Validation = Import-Csv $ValidationPath | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$ValidationPath"
    Write-Host "FINAL_STATUS=$($Validation.final_status)"
    Write-Host "DECISION=$($Validation.decision)"
    Write-Host "R2_AVG_COMPONENT_COVERAGE_RATIO=$($Validation.r2_avg_component_coverage_ratio)"
    Write-Host "R3_AVG_COMPONENT_COVERAGE_RATIO=$($Validation.r3_avg_component_coverage_ratio)"
    Write-Host "R3_COMPLETE/PARTIAL=$($Validation.r3_complete_explainability_count)/$($Validation.r3_partial_explainability_count)"
    Write-Host "QQQ_MA50_MAPPED_COUNT=$($Validation.qqq_ma50_regime_mapped_count)"
    Write-Host "LIQUIDITY_AVAILABLE_COUNT=$($Validation.liquidity_component_available_count)"
    Write-Host "MISSING_EXPECTED_COMPONENT_COUNT=$($Validation.missing_expected_component_count)"
    if ($PythonExit -ne 0 -or $Validation.final_status -like "BLOCKED_*") {
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
