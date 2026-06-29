Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_068_r1_weight_perturbation_backtest_harness.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\weight_perturbation"
$ValidationPath = Join-Path $OutputDir "V21_068_R1_VALIDATION_SUMMARY.csv"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $ValidationPath)) {
        throw "V21.068-R1 validation summary was not created."
    }
    $Validation = Import-Csv $ValidationPath | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$ValidationPath"
    Write-Host "FINAL_STATUS=$($Validation.final_status)"
    Write-Host "DECISION=$($Validation.decision)"
    Write-Host "PERTURBATION_COUNT=$($Validation.perturbation_count)"
    Write-Host "CURRENT_D_RECONSTRUCTION_MAX_ERROR=$($Validation.current_d_reconstruction_max_error)"
    Write-Host "CURRENT_D_RECONSTRUCTION_AVG_ERROR=$($Validation.current_d_reconstruction_avg_error)"
    Write-Host "EVALUATION_SOURCES_FOUND_COUNT=$($Validation.evaluation_sources_found_count)"
    Write-Host "MATURED_FORWARD_AVAILABLE=$($Validation.matured_forward_available)"
    Write-Host "TOP_CANDIDATE_PERTURBATION_ID=$($Validation.top_candidate_perturbation_id)"
    Write-Host "SHADOW_FORWARD_CANDIDATE_COUNT=$($Validation.shadow_forward_candidate_count)"
    if ($PythonExit -ne 0 -or $Validation.final_status -like "BLOCKED_*") {
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
