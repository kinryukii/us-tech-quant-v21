Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_059_r1_momentum_dynamic_abcd_versioned_experiment_harness.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic"
$SummaryPath = Join-Path $OutputDir "V21_059_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.059-R1"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "A0_RECOMPUTE_ALLOWED=FALSE"
Write-Host "BACKTEST_EXECUTED=FALSE"
Write-Host "FORWARD_LEDGER_APPEND_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.059-R1 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
