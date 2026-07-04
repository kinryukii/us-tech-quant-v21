$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_201_random_weight_pit_forward_backtest_consolidation.py"

python $Runner
