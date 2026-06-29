Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_057_r2_algorithmic_candidate_discovery_expansion.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\unified_pool"
$SummaryPath = Join-Path $OutputDir "V21_057_R2_SUMMARY.json"

Write-Host "STAGE_ID=V21.057-R2"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "FINAL_MOMENTUM_SCORING_IMPLEMENTED=FALSE"
Write-Host "FORCED_AUDIT_ELIGIBILITY_OVERRIDE_ALLOWED=FALSE"
Write-Host "BACKTEST_EXECUTED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.057-R2 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
