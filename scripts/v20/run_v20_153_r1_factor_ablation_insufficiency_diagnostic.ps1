$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_153_r1_factor_ablation_insufficiency_diagnostic.py"

python $Runner

