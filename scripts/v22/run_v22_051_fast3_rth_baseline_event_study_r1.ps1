param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Project virtual environment not found: $Python"
}

$Script = ".\scripts\v22\v22_051_fast3_rth_baseline_event_study_r1.py"
$Test = ".\scripts\v22\test_v22_051_fast3_rth_baseline_event_study_r1.py"

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_051_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.051 FAST3 RTH baseline event study"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script
if ($LASTEXITCODE -ne 0) {
    throw "PY_COMPILE failed with exit code $LASTEXITCODE"
}
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) {
    throw "TEST failed with exit code $LASTEXITCODE"
}
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=18" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Real RTH event study" -ForegroundColor Yellow
Write-Host "Processing is month-by-month; overlapping research events are expected." -ForegroundColor Yellow
& $Python $Script --execute
if ($LASTEXITCODE -ne 0) {
    throw "EVENT_STUDY failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
