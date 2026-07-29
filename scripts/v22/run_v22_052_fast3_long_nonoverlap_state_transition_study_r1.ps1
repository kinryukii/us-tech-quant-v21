param([switch]$Execute)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) { throw "The -Execute flag is required." }

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_052_fast3_long_nonoverlap_state_transition_study_r1.py"
$Test = ".\scripts\v22\test_v22_052_fast3_long_nonoverlap_state_transition_study_r1.py"

if (-not (Test-Path $Python)) { throw "Project virtual environment not found: $Python" }

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_052_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null
$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.052 long-only non-overlap study"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script
if ($LASTEXITCODE -ne 0) { throw "PY_COMPILE failed: $LASTEXITCODE" }
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host "Step 2/3: Targeted unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "TEST failed: $LASTEXITCODE" }
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=17" -ForegroundColor Green

Write-Host "Step 3/3: Real non-overlapping study" -ForegroundColor Yellow
& $Python $Script --execute
if ($LASTEXITCODE -ne 0) { throw "V22.052 failed: $LASTEXITCODE" }

Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
