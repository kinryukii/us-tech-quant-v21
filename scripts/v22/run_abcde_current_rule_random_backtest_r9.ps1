param([switch]$Execute)
if(-not $Execute){Write-Host 'Would execute independent R9 runner';exit 0}
& 'D:\us-tech-quant\.venv\Scripts\python.exe' "$PSScriptRoot\abcde_current_rule_random_backtest_r9.py"
exit $LASTEXITCODE
