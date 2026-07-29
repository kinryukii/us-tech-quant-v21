param([switch]$Execute)
$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"
if (-not $Execute) { throw "The -Execute flag is required." }

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_064t_fast3_cross_session_transition_atlas_r1.py"
$Test = ".\scripts\v22\test_v22_064t_fast3_cross_session_transition_atlas_r1.py"
foreach ($File in @($Python, $Script, $Test)) {
    if (-not (Test-Path $File)) { throw "Missing required file: $File" }
}

$ResultDir = "D:\us-tech-quant-results\v22\V22.064T_FAST3_CROSS_SESSION_TRANSITION_RETURN_ATLAS_R1"
$SummaryFile = Join-Path $ResultDir "v22_064t_summary.json"
$Running = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match "v22_064t_fast3_cross_session_transition_atlas"
}
if ($Running) { throw "V22.064T is already running." }

if (Test-Path $SummaryFile) {
    try {
        $Existing = Get-Content $SummaryFile -Raw | ConvertFrom-Json
        if ($Existing.final_status -eq "PASS") {
            Write-Host "V22.064T already completed. Existing PASS result is preserved." -ForegroundColor Green
            Write-Host "FINAL_STATUS=$($Existing.final_status)"
            Write-Host "FINAL_DECISION=$($Existing.final_decision)"
            Write-Host "DIAGNOSTIC_SURVIVING_TRANSITIONS=$($Existing.diagnostic_surviving_transitions)"
            Write-Host "NEXT_STAGE=$($Existing.next_stage)"
            Write-Host "SUMMARY_PATH=$SummaryFile"
            exit 0
        }
    } catch {}
}
if (Test-Path $ResultDir) { Remove-Item $ResultDir -Recurse -Force }

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_064t_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null
$env:TEMP = $PytestBase; $env:TMP = $PytestBase; $env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.064T cross-session transition atlas"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Step 1/3: Python compile" -ForegroundColor Yellow
& $Python -m py_compile $Script $Test
if ($LASTEXITCODE -ne 0) { throw "PY_COMPILE failed: $LASTEXITCODE" }
Write-Host "PY_COMPILE_EXIT_CODE=0" -ForegroundColor Green

Write-Host ""
Write-Host "Step 2/3: Targeted tests" -ForegroundColor Yellow
& $Python -m pytest $Test -q --basetemp="$PytestBase" -p no:cacheprovider
if ($LASTEXITCODE -ne 0) { throw "TEST failed: $LASTEXITCODE" }
Write-Host "TEST_EXIT_CODE=0" -ForegroundColor Green
Write-Host "TEST_COUNT=14" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Cross-session return atlas" -ForegroundColor Yellow
Write-Host "Only QQQ and SOXX Canonical partitions are opened." -ForegroundColor Yellow
Write-Host "No strategy, position or execution policy is created." -ForegroundColor Yellow
Write-Host "V22.062PR remains frozen and untouched." -ForegroundColor Yellow
Write-Host "Long quiet periods are normal. Do not press Ctrl+C." -ForegroundColor Yellow
& $Python $Script --execute
if ($LASTEXITCODE -ne 0) { throw "V22.064T atlas failed: $LASTEXITCODE" }
Write-Host ""
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
