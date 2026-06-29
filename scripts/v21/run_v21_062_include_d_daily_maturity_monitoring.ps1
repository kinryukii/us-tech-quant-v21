Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_062_include_d_daily_maturity_monitoring.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic\d_weight_optimized\v21_062_daily_monitoring"
$SummaryPath = Join-Path $OutputDir "V21_062_D_DAILY_MATURITY_MONITORING_SUMMARY.csv"

Write-Host "STAGE_ID=V21.062-INCLUDE-D"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_USE=FALSE"
Write-Host "TRADE_ACTION_CREATED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.062 D monitoring summary was not created."
    }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally {
    Pop-Location
}
