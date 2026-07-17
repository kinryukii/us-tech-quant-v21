param([switch]$Execute,[string]$RepoRoot='D:\us-tech-quant',[string]$DataRoot='D:\us-tech-quant-data',[string]$ResultsRoot='D:\us-tech-quant-results')
$ErrorActionPreference='Stop'
$r4=Join-Path $RepoRoot 'scripts\v22\run_v22_044_then_capture_abcde_snapshot_r4.ps1'
$py=Join-Path $RepoRoot '.venv\Scripts\python.exe'
$out=Join-Path $ResultsRoot 'abcde\ABCDE_DAILY_CONDITIONAL_BACKTEST_R7'
$r6=Join-Path $DataRoot 'derived_cache\abcde_real_rank_snapshots_r6\historical_rankings_master.parquet'
if(-not $Execute){Write-Host "Would run: $r4 -Execute, then conditional R7 analysis";exit 0}
& $r4 -Execute
if($LASTEXITCODE -ne 0){throw "R4_FAILED_EXIT_$LASTEXITCODE"}
$ranking=Join-Path $RepoRoot 'outputs\v21\V21.233_MOOMOO_ONLY_ABCDE_RERUN\abcde_strategy_ranking_master.csv'
& $py (Join-Path $RepoRoot 'scripts\v22\abcde_conditional_execution_backtest_r7.py') --master-path $r6 --results-root $out --official-ranking-path $ranking
exit $LASTEXITCODE
