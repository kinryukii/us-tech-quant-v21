Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_058_r4_listing_age_verification_and_local_history_gap_repair.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\momentum"
$SummaryPath = Join-Path $OutputDir "V21_058_R4_SUMMARY.json"

Write-Host "STAGE_ID=V21.058-R4"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "LISTING_REFERENCE_GRANTS_SCORE_ELIGIBILITY=FALSE"
Write-Host "PRICE_FABRICATION_ALLOWED=FALSE"
Write-Host "FORCED_TOP50_INCLUSION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) { throw "V21.058-R4 summary was not created." }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*") { exit 1 }
    if ($PythonExit -ne 0) { exit $PythonExit }
    exit 0
}
finally { Pop-Location }
