Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_065_price_refresh_then_d_maturity_recheck.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_065_price_refresh_then_d_maturity_recheck"
$SummaryPath = Join-Path $OutputDir "V21_065_PRICE_REFRESH_RECHECK_SUMMARY.csv"

Write-Host "STAGE_ID=V21.065"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "APPROVED_REFRESH_PATH=V20.199D"
Write-Host "ABCD_COMPARISON_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.065 price-refresh recheck summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
