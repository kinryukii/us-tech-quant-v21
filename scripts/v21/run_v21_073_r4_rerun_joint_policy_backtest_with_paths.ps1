Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$Validation = Join-Path $RepoRoot "outputs\v21\v21_073\V21_073_R4_VALIDATION_SUMMARY.csv"
Push-Location $RepoRoot
try {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptDir "run_v21_073_r3_causal_exit_simulator.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    python (Join-Path $ScriptDir "v21_073_r4_rerun_joint_policy_backtest_with_paths.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    $Row = Import-Csv $Validation | Select-Object -First 1
    Write-Host "VALIDATION_SUMMARY=$Validation"
    Write-Host "FINAL_STATUS=$($Row.final_status)"
    Write-Host "DECISION=$($Row.decision)"
    Write-Host "PATH_ROWS=$($Row.path_rows)"
    Write-Host "OBSERVATIONS_COVERED=$($Row.observations_covered)"
    Write-Host "BEST_TOP20_PATH_BASED_POLICY=$($Row.best_top20_path_based_policy)"
    Write-Host "BEST_TOP50_PATH_BASED_POLICY=$($Row.best_top50_path_based_policy)"
    Write-Host "BEST_RISK_PROXY_POLICY=$($Row.best_risk_proxy_policy)"
    exit 0
}
finally { Pop-Location }
