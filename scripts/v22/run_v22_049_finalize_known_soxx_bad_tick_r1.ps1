param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

if (Test-Path ".\.venv\Scripts\python.exe") {
    $Python = ".\.venv\Scripts\python.exe"
}
else {
    throw "Project virtual environment not found: .\.venv\Scripts\python.exe"
}

$Script = ".\scripts\v22\v22_049_finalize_known_soxx_bad_tick_r1.py"
$Test   = ".\scripts\v22\test_v22_049_finalize_known_soxx_bad_tick_r1.py"

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_049_$RunStamp"

New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

# Force Python and pytest to use a known writable location.
$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.049 SOXX known bad-tick finalization"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "PYTHON=$Python"
Write-Host "PYTEST_BASETEMP=$PytestBase"

if (-not (Test-Path $Script)) {
    throw "Python maintenance script not found: $Script"
}

if (-not (Test-Path $Test)) {
    throw "Test file not found: $Test"
}

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow

& $Python -m py_compile $Script

if ($LASTEXITCODE -ne 0) {
    throw "PY_COMPILE failed with exit code $LASTEXITCODE"
}

Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted tests" -ForegroundColor Yellow

& $Python -m pytest `
    $Test `
    -q `
    --basetemp="$PytestBase" `
    -p no:cacheprovider

if ($LASTEXITCODE -ne 0) {
    throw "TEST failed with exit code $LASTEXITCODE"
}

Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=4" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Execute real maintenance" -ForegroundColor Yellow

& $Python $Script --execute

if ($LASTEXITCODE -ne 0) {
    throw "Real maintenance failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green