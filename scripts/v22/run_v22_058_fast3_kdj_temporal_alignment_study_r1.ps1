param(
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
Set-Location "D:\us-tech-quant"

if (-not $Execute) {
    throw "The -Execute flag is required."
}

$Python = ".\.venv\Scripts\python.exe"
$Script = ".\scripts\v22\v22_058_fast3_kdj_temporal_alignment_study_r1.py"
$Test = ".\scripts\v22\test_v22_058_fast3_kdj_temporal_alignment_study_r1.py"
$ResultDir = "D:\us-tech-quant-results\v22\V22.058_FAST3_KDJ_TEMPORAL_ALIGNMENT_STUDY_R1"

foreach ($Required in @($Python, $Script, $Test)) {
    if (-not (Test-Path $Required)) {
        throw "Missing required file: $Required"
    }
}

$Pattern = "v22_058_fast3_kdj_temporal_alignment_study_r1"
$Running = Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -match [regex]::Escape($Pattern)
    }

if ($Running) {
    $Running |
        Select-Object ProcessId, CreationDate, CommandLine |
        Format-List
    throw "V22.058 is already running. Duplicate execution is blocked."
}

$TempRoot = "D:\us-tech-quant-results\pytest_temp"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss_fff"
$PytestBase = Join-Path $TempRoot "v22_058_$RunStamp"
New-Item -ItemType Directory -Force -Path $PytestBase | Out-Null

$env:TEMP = $PytestBase
$env:TMP = $PytestBase
$env:TMPDIR = $PytestBase

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " V22.058 FAST3 KDJ temporal-alignment study"
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
Write-Host "TEST_COUNT=22" -ForegroundColor Green

Write-Host ""
Write-Host "Step 3/3: Frozen KDJ timing comparison" -ForegroundColor Yellow
Write-Host "Variants: STRICT_SAME_BAR_KDJ / RECENT_3BAR_KDJ / NO_KDJ_CONTROL"
Write-Host "All non-KDJ rules, costs, sizing and exits remain frozen."
Write-Host "This reads the 582 Canonical partitions. Long quiet periods are normal."
Write-Host "Do not press Ctrl+C."

& $Python $Script --execute
if ($LASTEXITCODE -ne 0) {
    throw "V22.058 study failed: $LASTEXITCODE"
}

$SummaryFile = Join-Path $ResultDir "v22_058_summary.json"
$QualificationFile = Join-Path $ResultDir "v22_058_qualification_table.csv"
$PeriodFile = Join-Path $ResultDir "v22_058_period_summary.csv"

foreach ($Output in @($SummaryFile, $QualificationFile, $PeriodFile)) {
    if (-not (Test-Path $Output)) {
        throw "Expected output missing: $Output"
    }
}

$Summary = Get-Content $SummaryFile -Raw | ConvertFrom-Json
$Qualification = Import-Csv $QualificationFile
$Period = Import-Csv $PeriodFile

Write-Host ""
Write-Host "========== V22.058 qualification ==========" -ForegroundColor Yellow
$Qualification |
    Select-Object `
        variant,
        full_history_trade_count,
        validation_trade_count,
        confirmation_trade_count,
        sample_evaluable,
        direction_positive_both_periods,
        pit_excess_positive_both_periods,
        research_candidate_for_next_stage,
        kdj_incremental_mean_support |
    Format-Table -AutoSize

Write-Host ""
Write-Host "========== Validation / Confirmation performance ==========" -ForegroundColor Yellow
$Period |
    Where-Object {
        $_.study_period -in @(
            "2023-2024_VALIDATION",
            "2025-2026_YTD_CONFIRMATION"
        )
    } |
    ForEach-Object {
        [pscustomobject]@{
            Variant       = $_.variant
            Period        = $_.study_period
            Trades        = [int]$_.trade_count
            MeanNetBps    = if ($_.mean_instrument_net_return -ne "") {
                [math]::Round([double]$_.mean_instrument_net_return * 10000, 2)
            } else { $null }
            MedianNetBps  = if ($_.median_instrument_net_return -ne "") {
                [math]::Round([double]$_.median_instrument_net_return * 10000, 2)
            } else { $null }
            PositivePct   = if ($_.positive_rate -ne "") {
                [math]::Round([double]$_.positive_rate * 100, 2)
            } else { $null }
            ProfitFactor  = if ($_.profit_factor -ne "") {
                [math]::Round([double]$_.profit_factor, 3)
            } else { $null }
            PITExcessBps  = if ($_.mean_entry_excess_pit_60m -ne "") {
                [math]::Round([double]$_.mean_entry_excess_pit_60m * 10000, 2)
            } else { $null }
            MaxDrawdownPct = if ($_.max_drawdown -ne "") {
                [math]::Round([double]$_.max_drawdown * 100, 2)
            } else { $null }
        }
    } |
    Sort-Object Variant, Period |
    Format-Table -AutoSize

Write-Host ""
Write-Host "FINAL_STATUS=$($Summary.final_status)" -ForegroundColor Green
Write-Host "FINAL_DECISION=$($Summary.final_decision)" -ForegroundColor Green
Write-Host "SUMMARY_PATH=$SummaryFile"
Write-Host "RUNNER_FINAL_STATUS=PASS" -ForegroundColor Green
