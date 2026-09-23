$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_191_daily_runner_regression_with_data_trust_gate_only.py"

python $Runner
