param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$PriceCsv = "",
    [double]$CostBps = 5.0,
    [string]$EndDate = "2026-07-13"
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$ScriptPath = Join-Path $RepoRoot "scripts\v22\abcde_all_history_execution_backtest.py"
$RankingPath = Join-Path $RepoRoot "inputs\abcde_all_uploaded_rankings_master.csv"
$OutputDir = Join-Path $RepoRoot "outputs\v22\ABCDE_ALL_HISTORY_EXECUTION_BACKTEST_R1"

if (-not (Test-Path $ScriptPath)) { throw "Missing script: $ScriptPath" }
if (-not (Test-Path $RankingPath)) { throw "Missing ranking master: $RankingPath" }

if ([string]::IsNullOrWhiteSpace($PriceCsv)) {
    $Candidates = @(
        (Join-Path $RepoRoot "outputs\v21\V21.199_R4_RATE_LIMITED_HISTORY_KLINE_FETCH_AND_RESUME\moomoo_daily_ohlcv_staging_qfq_r4.csv"),
        (Join-Path $RepoRoot "outputs\v20\price_history\V20_199D_CANONICAL_HISTORICAL_OHLCV.csv")
    )
    $PriceCsv = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($PriceCsv) -or -not (Test-Path $PriceCsv)) {
    throw "No price CSV found. Pass -PriceCsv with the latest QFQ canonical daily OHLCV file."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

& $Python $ScriptPath `
    --rankings $RankingPath `
    --prices $PriceCsv `
    --output-dir $OutputDir `
    --start-date "2026-06-17" `
    --end-date $EndDate `
    --cost-bps $CostBps `
    --missing-price-policy redistribute

if ($LASTEXITCODE -ne 0) { throw "Backtest failed with exit code $LASTEXITCODE" }

Write-Host "`n=== TOP RESULTS ===" -ForegroundColor Cyan
Import-Csv (Join-Path $OutputDir "policy_summary.csv") |
    Select-Object -First 15 policy,total_return,max_drawdown,excess_vs_qqq,cumulative_one_way_turnover,rebalance_count,average_gross_exposure |
    Format-Table -AutoSize

Write-Host "`nOutputDir=$OutputDir" -ForegroundColor Green
