Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
$StageScript = Join-Path $ScriptDir "v21_056_r2_a0_schema_bridge_and_canonical_control_view.py"
$OutputDir = Join-Path $RepoRoot "outputs\v21\experiments\version_control"
$SummaryPath = Join-Path $OutputDir "V21_056_R2_SUMMARY.json"

Write-Host "STAGE_ID=V21.056-R2"
Write-Host "FROZEN_VERSION_ID=A0_CURRENT_TESTING_LOCKED"
Write-Host "RESEARCH_ONLY=TRUE"
Write-Host "SOURCE_MUTATION_ALLOWED=FALSE"
Write-Host "OFFICIAL_MUTATION_ALLOWED=FALSE"
Write-Host "REAL_BOOK_MUTATION_ALLOWED=FALSE"
Write-Host "BROKER_MUTATION_ALLOWED=FALSE"

Push-Location $RepoRoot
try {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    python $StageScript
    $PythonExit = $LASTEXITCODE
    if (-not (Test-Path $SummaryPath)) {
        throw "V21.056-R2 did not create the required summary."
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
