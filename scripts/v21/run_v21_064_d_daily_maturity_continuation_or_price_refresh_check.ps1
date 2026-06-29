Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_064_d_daily_maturity_continuation_or_price_refresh_check.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_064_daily_maturity_continuation_or_price_refresh_check"
$SummaryPath = Join-Path $OutputDir "V21_064_D_MATURITY_CONTINUATION_CHECK_SUMMARY.csv"

Write-Host "STAGE_ID=V21.064"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_USE=FALSE"
Write-Host "ABCD_COMPARISON_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.064 continuation-check summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
