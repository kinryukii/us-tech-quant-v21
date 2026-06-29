Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_067_r2_factor_component_lineage_resolver_and_explainability_rerun.py"
$ValidationPath = Join-Path $RepoRoot "outputs\v21\explainability\V21_067_R2_VALIDATION_SUMMARY.csv"

Push-Location $RepoRoot
try {
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $ValidationPath)) {
        throw "V21.067-R2 validation summary was not created."
    }
    $Validation = Import-Csv $ValidationPath | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$ValidationPath"
    Write-Host "FINAL_STATUS=$($Validation.final_status)"
    Write-Host "DECISION=$($Validation.decision)"
    Write-Host "SELECTED_COMPONENT_COUNT=$($Validation.selected_component_count)"
    Write-Host "SELECTED_TECHNICAL_SUBFACTOR_COUNT=$($Validation.selected_technical_subfactor_count)"
    Write-Host "AVG_COMPONENT_COVERAGE_RATIO=$($Validation.avg_component_coverage_ratio)"
    if ($PythonExit -ne 0 -or $Validation.final_status -like "BLOCKED_*") {
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
