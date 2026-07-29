param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_057_fast3_multifactor_state_machine_backtest_r1.py"
$Test = ".\scripts\v22\test_v22_057_fast3_multifactor_state_machine_backtest_r1.py"

foreach ($File in @($Python, $Script, $Test)) {
    if (-not (Test-Path $File)) {
        throw "Missing required file: $File"
    }
}

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_057_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null
$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.057 FAST3 multifactor state-machine study"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script $Test
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
Write-Host "TEST_COUNT=18" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Full frozen multifactor backtest" -ForegroundColor Yellow
Write-Host "This reads all six Canonical ETF partitions." -ForegroundColor Yellow
Write-Host "Long quiet periods during factor construction are normal." -ForegroundColor Yellow
Write-Host "Do not press Ctrl+C." -ForegroundColor Yellow

& $Python $Script --execute
if ($LASTEXITCODE -ne 0) {
    throw "V22.057 study failed: $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
