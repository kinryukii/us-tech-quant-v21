$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_177_data_trust_multiday_daily_runner_observation_plan.py"

python $Runner
