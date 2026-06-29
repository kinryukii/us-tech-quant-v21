Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_067_r1_factor_explainability_ledger.py"
$ValidationPath = Join-Path $RepoRoot "outputs\v21\explainability\V21_067_R1_VALIDATION_SUMMARY.csv"

Push-Location $RepoRoot
try {
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $ValidationPath)) {
        throw "V21.067-R1 validation summary was not created."
    }
    $Validation = Import-Csv $ValidationPath | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$ValidationPath"
    Write-Host "FINAL_STATUS=$($Validation.final_status)"
    Write-Host "DECISION=$($Validation.decision)"
    if ($PythonExit -ne 0 -or $Validation.final_status -like "BLOCKED_*") {
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
