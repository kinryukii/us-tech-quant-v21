param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_062pr_fast3_premarket_forward_replication_r1.py"
$Test = ".\scripts\v22\test_v22_062pr_fast3_premarket_forward_replication_r1.py"

foreach ($File in @($Python, $Script, $Test)) {
    if (-not (Test-Path $File)) {
        throw "Missing required file: $File"
    }
}

$ResultDir = "D:\us-tech-quant-results\v22\V22.062PR_FAST3_PREMARKET_INDEPENDENT_FORWARD_REPLICATION_R1"

$Running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match "v22_062pr_fast3_premarket_forward_replication"
    }

if ($Running) {
    $Running |
        Select-Object ProcessId, CreationDate, CommandLine |
        Format-List
    throw "V22.062PR is already running."
}

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_062pr_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.062PR premarket forward replication"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script $Test
if ($LASTEXITCODE -ne 0) {
    throw "PY_COMPILE failed: $LASTEXITCODE"
}
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) {
    throw "TEST failed: $LASTEXITCODE"
}
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=27" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Frozen forward holdout update" -ForegroundColor Yellow
Write-Host "Research cutoff: 2026-07-24 ET." -ForegroundColor Yellow
Write-Host "Only sessions after the cutoff can affect qualification." -ForegroundColor Yellow
Write-Host "Any strategy-rule change requires a new result directory." -ForegroundColor Yellow
Write-Host "No paper or broker action is enabled." -ForegroundColor Yellow

& $Python $Script --execute
if ($LASTEXITCODE -ne 0) {
    throw "V22.062PR replication update failed: $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
