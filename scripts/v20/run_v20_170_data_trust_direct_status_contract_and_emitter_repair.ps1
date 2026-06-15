$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_data_trust_direct_status_contract_and_emitter_repair.py"

python $Runner

