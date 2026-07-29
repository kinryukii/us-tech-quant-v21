param([switch]$Execute)
$ErrorActionPreference="Stop"
Set-Location "D:\us-tech-quant"
if(-not $Execute){throw "The -Execute flag is required."}
$Python=".\.venv\Scripts\python.exe"
$Script=".\scripts\v22\v22_050_fast3_six_etf_minute_tradability_audit_r1.py"
$Test=".\scripts\v22\test_v22_050_fast3_six_etf_minute_tradability_audit_r1.py"
if(-not(Test-Path $Python)){throw "Python not found: $Python"}
$Base="D:\us-tech-quant-results\pytest_temp\v22_050_$(Get-Date -Format 'yyyyMMdd_HHmmss_fff')"
New-Item -ItemType Directory -Force -Path $Base|Out-Null
$env:TEMP=$Base;$env:TMP=$Base;$env:TMPDIR=$Base
Write-Host "";Write-Host "==============================================" -ForegroundColor Cyan;Write-Host " V22.050 six-ETF minute tradability audit";Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script
if($LASTEXITCODE-ne 0){throw "PY_COMPILE failed: $LASTEXITCODE"}
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green
Write-Host "Step 2/3: Unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$Base" -p no:cacheprovider
if($LASTEXITCODE-ne 0){throw "TEST failed: $LASTEXITCODE"}
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green;Write-Host "TEST_COUNT=12" -ForegroundColor Green
Write-Host "Step 3/3: Real read-only audit" -ForegroundColor Yellow
& $Python $Script --execute
if($LASTEXITCODE-ne 0){throw "AUDIT failed: $LASTEXITCODE"}
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
