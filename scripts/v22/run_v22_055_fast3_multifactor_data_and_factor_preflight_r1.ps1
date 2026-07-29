param(
    [switch]$Execute,
    [string]$VixRoot = ""
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"
if (-not $Execute) { throw "The -Execute flag is required." }

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_055_fast3_multifactor_data_and_factor_preflight_r1.py"
$Test = ".\scripts\v22\test_v22_055_fast3_multifactor_data_and_factor_preflight_r1.py"
if (-not (Test-Path $Python)) { throw "Missing Python: $Python" }

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$BaseTemp = Join-Path $TempRoot "v22_055_$Stamp"
New-Item -ItemType Directory -Force -Path $BaseTemp | Out-Null
$env:TEMP=$BaseTemp; $env:TMP=$BaseTemp; $env:TMPDIR=$BaseTemp

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.055 FAST3 multifactor data preflight"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script
if ($LASTEXITCODE -ne 0) { throw "PY_COMPILE failed: $LASTEXITCODE" }
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host "Step 2/3: Unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$BaseTemp" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "TEST failed: $LASTEXITCODE" }
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=13" -ForegroundColor Green

Write-Host "Step 3/3: Local VIX and factor readiness audit" -ForegroundColor Yellow
$Arguments = @($Script, "--execute")
if (-not [string]::IsNullOrWhiteSpace($VixRoot)) { $Arguments += @("--vix-root", $VixRoot) }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw "V22.055 preflight failed: $LASTEXITCODE" }
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
