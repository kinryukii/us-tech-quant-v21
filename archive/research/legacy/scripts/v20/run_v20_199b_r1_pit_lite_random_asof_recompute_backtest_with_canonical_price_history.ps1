$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_199b_r1_pit_lite_random_asof_recompute_backtest_with_canonical_price_history.py"

python $Runner
