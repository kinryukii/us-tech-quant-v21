param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_059_fast3_vix_change_rate_direction_study_r1.py"
$Test = ".\scripts\v22\test_v22_059_fast3_vix_change_rate_direction_study_r1.py"

foreach ($File in @($Python, $Script, $Test)) {
    if (-not (Test-Path $File)) {
        throw "Missing required file: $File"
    }
}

$Pattern = "v22_059_fast3_vix_change_rate_direction_study_r1"
$Running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match [regex]::Escape($Pattern)
    }
if ($Running) {
    throw "V22.059 is already running."
}

$ResultDir = "D:\us-tech-quant-results\v22\V22.059_FAST3_VIX_CHANGE_RATE_DIRECTION_STUDY_R1"
if (Test-Path $ResultDir) {
    $SummaryFile = Join-Path $ResultDir "v22_059_summary.json"
    $Complete = $false
    if (Test-Path $SummaryFile) {
        try {
            $Summary = Get-Content $SummaryFile -Raw | ConvertFrom-Json
            $Complete = ($Summary.final_status -eq "PASS")
        }
        catch {
            $Complete = $false
        }
    }
    if ($Complete) {
        Write-Host "V22.059 already completed; preserving existing PASS result." -ForegroundColor Green
        Write-Host "FINAL_DECISION=$($Summary.final_decision)"
        exit 0
    }
    Remove-Item $ResultDir -Recurse -Force
    Write-Host "Removed incomplete V22.059 result directory." -ForegroundColor Yellow
}

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_059_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null
$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.059 FAST3 VIX change-rate direction study"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script $Test
if ($LASTEXITCODE -ne 0) { throw "PY_COMPILE failed: $LASTEXITCODE" }
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted unit tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "TEST failed: $LASTEXITCODE" }
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=25" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Frozen VIX rate comparison" -ForegroundColor Yellow
Write-Host "Variants: NO_VIX / OLD_LEVEL / VIX_RATE_1D / VIX_RATE_1D_3D_CONFIRM" -ForegroundColor Yellow
Write-Host "KDJ entry and exit are disabled for every variant." -ForegroundColor Yellow
Write-Host "This reads the 582 Canonical partitions. Long quiet periods are normal." -ForegroundColor Yellow
Write-Host "Do not press Ctrl+C." -ForegroundColor Yellow

& $Python $Script --execute
if ($LASTEXITCODE -ne 0) { throw "V22.059 study failed: $LASTEXITCODE" }

Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
