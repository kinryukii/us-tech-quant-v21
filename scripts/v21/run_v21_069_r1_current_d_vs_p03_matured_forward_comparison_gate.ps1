Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_069_r1_current_d_vs_p03_matured_forward_comparison_gate.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\forward_comparison"
$ValidationPath = Join-Path $OutputDir "V21_069_R1_VALIDATION_SUMMARY.csv"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $ValidationPath)) {
        throw "V21.069-R1 validation summary was not created."
    }
    $Validation = Import-Csv $ValidationPath | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$ValidationPath"
    Write-Host "FINAL_STATUS=$($Validation.final_status)"
    Write-Host "DECISION=$($Validation.decision)"
    Write-Host "MATURED_FORWARD_AVAILABLE=$($Validation.matured_forward_available)"
    Write-Host "MATURED_OBSERVATION_COUNT=$($Validation.matured_observation_count)"
    Write-Host "AVAILABLE_MATURED_WINDOWS=$($Validation.available_matured_windows)"
    Write-Host "TOP20_P03_VS_CURRENT_D_RESULT=$($Validation.top20_p03_vs_current_d_result)"
    Write-Host "TOP50_P03_VS_CURRENT_D_RESULT=$($Validation.top50_p03_vs_current_d_result)"
    Write-Host "RECOMMENDED_ACTION=$($Validation.recommended_action)"
    if ($PythonExit -ne 0 -or $Validation.final_status -like "BLOCKED_*") {
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
