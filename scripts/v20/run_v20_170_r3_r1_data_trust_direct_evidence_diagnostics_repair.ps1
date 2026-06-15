$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r3_r1_data_trust_direct_evidence_diagnostics_repair.py"

python $Runner
