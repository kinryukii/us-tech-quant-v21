Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_060_r2_multi_seed_random_asof_abcd_robustness_backtest.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\random_backtests"
$SummaryPath = Join-Path $OutputDir "V21_060_R2_RANDOM_BACKTEST_SUMMARY.json"

Write-Host "STAGE_ID=V21.060-R2"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "A0_REPLAYED=FALSE"
Write-Host "PRODUCTION_ADOPTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.060-R2 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
