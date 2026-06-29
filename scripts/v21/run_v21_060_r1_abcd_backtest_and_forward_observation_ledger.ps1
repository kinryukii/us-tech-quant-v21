Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_060_r1_abcd_backtest_and_forward_observation_ledger.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic"
$SummaryPath = Join-Path $OutputDir "V21_060_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.060-R1"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "A0_HISTORICAL_REPLAY_ALLOWED=FALSE"
Write-Host "A0_RECOMPUTE_ALLOWED=FALSE"
Write-Host "OFFICIAL_RECOMMENDATIONS_CREATED=FALSE"
Write-Host "BROKER_ACTIONS_CREATED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.060-R1 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
