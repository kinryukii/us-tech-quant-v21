$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_193_final_operator_acceptance_with_data_trust_gate_only.py"

python $Runner
