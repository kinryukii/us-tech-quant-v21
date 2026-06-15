$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_163_bound_shadow_score_and_rank_movement_cap_repair.py"

python $Runner

