Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_066_d_maturity_wait_continuation_after_price_refresh.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_066_maturity_wait_continuation_after_price_refresh"
$SummaryPath = Join-Path $OutputDir "V21_066_D_WAIT_CONTINUATION_SUMMARY.csv"

Write-Host "STAGE_ID=V21.066"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "PRICE_REFRESH_TRIGGERED=FALSE"
Write-Host "ABCD_COMPARISON_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.066 wait-continuation summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
