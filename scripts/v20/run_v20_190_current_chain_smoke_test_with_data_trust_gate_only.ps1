$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_190_current_chain_smoke_test_with_data_trust_gate_only.py"

python $Runner
