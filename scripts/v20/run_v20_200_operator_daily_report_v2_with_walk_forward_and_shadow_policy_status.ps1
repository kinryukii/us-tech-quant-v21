$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_200_operator_daily_report_v2_with_walk_forward_and_shadow_policy_status.py"

python $Runner
