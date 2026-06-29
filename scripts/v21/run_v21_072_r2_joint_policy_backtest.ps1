Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$R1 = Join-Path $ScriptDir "run_v21_072_r1_selection_entry_exit_policy_grid_builder.ps1"
$Script = Join-Path $ScriptDir "v21_072_r2_joint_policy_backtest.py"
$Validation = Join-Path $RepoRoot "outputs\v21\v21_072\V21_072_R2_VALIDATION_SUMMARY.csv"
Push-Location $RepoRoot
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File $R1
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python $Script
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "BEST_POLICY_TOP20_10D=$($Row.best_policy_top20_10d)"
    Write-Host "BEST_POLICY_TOP50_10D=$($Row.best_policy_top50_10d)"
    Write-Host "BEST_RISK_ADJUSTED_POLICY=$($Row.best_risk_adjusted_policy)"
    exit 0
}
finally { Pop-Location }
