Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_058_r1_unified_momentum_leadership_tracker.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\momentum"
$SummaryPath = Join-Path $OutputDir "V21_058_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.058-R1"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "FORCED_AUDIT_BOOST_ALLOWED=FALSE"
Write-Host "TRADE_RECOMMENDATIONS_CREATED=FALSE"
Write-Host "BACKTEST_EXECUTED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.058-R1 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*" -or $Summary.FINAL_STATUS -like "BLOCKED_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
