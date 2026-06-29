Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Script = Join-Path $ScriptDir "v21_072_r1_selection_entry_exit_policy_grid_builder.py"
$Validation = Join-Path $RepoRoot "outputs\v21\v21_072\V21_072_R1_VALIDATION_SUMMARY.csv"
Push-Location $RepoRoot
try {
    python $Script
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "TOTAL_POLICY_COMBINATIONS=$($Row.total_policy_combinations)"
    exit 0
}
finally { Pop-Location }
