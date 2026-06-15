$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_109_r8_second_round_simulated_weight_strict_equity_rerank_runner.py"

python $Runner
