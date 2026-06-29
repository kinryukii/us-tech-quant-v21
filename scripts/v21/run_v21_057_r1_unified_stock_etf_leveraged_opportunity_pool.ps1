Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_057_r1_unified_stock_etf_leveraged_opportunity_pool.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\unified_pool"
$SummaryPath = Join-Path $OutputDir "V21_057_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.057-R1"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "MOMENTUM_SCORING_IMPLEMENTED=FALSE"
Write-Host "BACKTEST_EXECUTED=FALSE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.057-R1 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*" -or $Summary.FINAL_STATUS -like "BLOCKED_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
