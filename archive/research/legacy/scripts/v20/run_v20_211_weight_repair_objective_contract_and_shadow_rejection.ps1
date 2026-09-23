$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_211_weight_repair_objective_contract_and_shadow_rejection.py"

python $Runner
