param([string]$DataRoot='D:\us-tech-quant-data',[string]$ResultsRoot='D:\us-tech-quant-results',[switch]$Execute)
$py='D:\us-tech-quant-envs\abcde-moomoo-sdk-10.8.6808\Scripts\python.exe';$s=Join-Path $PSScriptRoot 'abcde_real_snapshot_execution_backtest_r3.py';if(!$Execute){"WhatIf: $py $s";exit 0};& $py $s --data-root $DataRoot --results-root $ResultsRoot;exit $LASTEXITCODE
