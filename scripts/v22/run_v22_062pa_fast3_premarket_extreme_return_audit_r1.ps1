param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_062pa_fast3_premarket_extreme_return_audit_r1.py"
$Test = ".\scripts\v22\test_v22_062pa_fast3_premarket_extreme_return_audit_r1.py"

foreach ($File in @($Python, $Script, $Test)) {
    if (-not (Test-Path $File)) {
        throw "Missing required file: $File"
    }
}

$ResultDir = "D:\us-tech-quant-results\v22\V22.062PA_FAST3_PREMARKET_EXTREME_RETURN_AUDIT_R1"
$SummaryFile = Join-Path $ResultDir "v22_062pa_summary.json"

$Running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match "v22_062pa_fast3_premarket_extreme_return_audit"
    }

if ($Running) {
    $Running |
        Select-Object ProcessId, CreationDate, CommandLine |
        Format-List
    throw "V22.062PA is already running."
}

if (Test-Path $SummaryFile) {
    try {
        $Existing = Get-Content $SummaryFile -Raw | ConvertFrom-Json
        if ($Existing.final_status -eq "PASS") {
            Write-Host "V22.062PA already completed. Existing PASS result is preserved." -ForegroundColor Green
            Write-Host "FINAL_STATUS=$($Existing.final_status)"
            Write-Host "FINAL_DECISION=$($Existing.final_decision)"
            Write-Host "NEXT_STAGE=$($Existing.next_stage)"
            Write-Host "SUMMARY_PATH=$SummaryFile"
            exit 0
        }
    }
    catch {
        Write-Host "Existing V22.062PA summary is invalid; incomplete results will be replaced." -ForegroundColor Yellow
    }
}

if (Test-Path $ResultDir) {
    Remove-Item $ResultDir -Recurse -Force
    Write-Host "Removed incomplete V22.062PA result directory." -ForegroundColor Yellow
}

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_062pa_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.062PA premarket extreme-return audit"
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
Write-Host "TEST_COUNT=17" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Targeted extreme-return audit" -ForegroundColor Yellow
Write-Host "This does not rerun the strategy." -ForegroundColor Yellow
Write-Host "Only partitions required by influential trades are opened." -ForegroundColor Yellow

& $Python $Script --execute
if ($LASTEXITCODE -ne 0) {
    throw "V22.062PA audit failed: $LASTEXITCODE"
}

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
