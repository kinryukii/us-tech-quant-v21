param(
  [string]$DataRoot='D:\us-tech-quant-data', [string]$ResultsRoot='D:\us-tech-quant-results',
  [string]$Host='127.0.0.1', [int]$Port=18441, [string]$Start='2000-01-01', [string]$End=(Get-Date -Format 'yyyy-MM-dd'),
  [switch]$SkipFetch, [switch]$Execute
)
$py='D:\us-tech-quant-envs\abcde-moomoo-sdk-10.8.6808\Scripts\python.exe'
$script=Join-Path $PSScriptRoot 'abcde_long_horizon_random_execution_backtest_r2.py'
$args=@($script,'--data-root',$DataRoot,'--results-root',$ResultsRoot,'--host',$Host,'--port',$Port,'--start',$Start,'--end',$End)
if($SkipFetch){$args+='--skip-fetch'}
if(-not $Execute){Write-Output ('WhatIf: & '+$py+' '+($args -join ' ')); exit 0}
& $py @args; exit $LASTEXITCODE
