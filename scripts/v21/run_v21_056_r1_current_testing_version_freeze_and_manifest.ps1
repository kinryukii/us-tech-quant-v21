Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_056_r1_current_testing_version_freeze_and_manifest.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\version_control"
$SummaryPath = Join-Path $OutputDir "V21_056_R1_SUMMARY.json"

Write-Host "STAGE_ID=V21.056-R1"
Write-Host "FROZEN_VERSION_ID=A0_CURRENT_TESTING_LOCKED"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "OFFICIAL_USE_ALLOWED=FALSE"
Write-Host "PRODUCTION_ADOPTION_ALLOWED=FALSE"
Write-Host "REAL_BOOK_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_EXECUTION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.056-R1 did not create the required summary."
    }
    $Summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host "FINAL_STATUS=$($Summary.FINAL_STATUS)"
    Write-Host "DECISION=$($Summary.DECISION)"
    if ($Summary.FINAL_STATUS -like "FAIL_*" -or $Summary.FINAL_STATUS -like "BLOCKED_*") {
        exit 1
    }
    if ($PythonExit -ne 0) {
        exit $PythonExit
    }
    exit 0
}
finally {
    Pop-Location
}
