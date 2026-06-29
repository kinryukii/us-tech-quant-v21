Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_062_r1_abcd_continued_maturity_monitoring_and_daily_refresh.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\momentum_dynamic"
$SummaryPath = Join-Path $OutputDir "V21_062_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.062-R1"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "DAILY_MATURITY_REFRESH=TRUE"
Write-Host "SOURCE_LEDGER_MUTATION_ALLOWED=FALSE"
Write-Host "PRODUCTION_ADOPTION_ALLOWED=FALSE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.062-R1 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
