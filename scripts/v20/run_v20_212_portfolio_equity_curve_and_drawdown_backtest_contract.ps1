$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_212_portfolio_equity_curve_and_drawdown_backtest_contract.py"

python $Runner
