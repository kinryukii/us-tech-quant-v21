param(
    [switch]$Execute,
    [string]$SourceCsv = ""
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

$Script = ".\scripts\v22\v22_056_fast3_cboe_daily_vix_ingest_and_pit_regime_r1.py"
$Test = ".\scripts\v22\test_v22_056_fast3_cboe_daily_vix_ingest_and_pit_regime_r1.py"

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_056_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.056 official Cboe daily VIX ingest"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script
if ($LASTEXITCODE -ne 0) {
    throw "PY_COMPILE failed: $LASTEXITCODE"
}
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) {
    throw "TEST failed: $LASTEXITCODE"
}
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=14" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Official daily VIX ingest" -ForegroundColor Yellow
Write-Host "No intraday VIX proxy will be used." -ForegroundColor Yellow

$Arguments = @($Script, "--execute")
if (-not [string]::IsNullOrWhiteSpace($SourceCsv)) {
    $Arguments += @("--source-csv", $SourceCsv)
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "V22.056 ingest failed: $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
