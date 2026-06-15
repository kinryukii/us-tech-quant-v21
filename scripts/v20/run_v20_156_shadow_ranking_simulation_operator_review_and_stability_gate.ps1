$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_156_shadow_ranking_simulation_operator_review_and_stability_gate.py"

python $Runner

