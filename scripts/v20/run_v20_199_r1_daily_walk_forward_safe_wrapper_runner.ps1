$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_199_r1_daily_walk_forward_safe_wrapper_runner.py"

python $Runner
