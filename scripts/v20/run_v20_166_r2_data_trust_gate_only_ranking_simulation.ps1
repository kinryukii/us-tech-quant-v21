$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_166_r2_data_trust_gate_only_ranking_simulation.py"

python $Runner

