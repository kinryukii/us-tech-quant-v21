$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r1b_data_trust_upstream_pit_producer_patch_plan.py"

python $Runner
