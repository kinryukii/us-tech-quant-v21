$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_192_current_chain_release_candidate_with_data_trust_gate_only.py"

python $Runner
