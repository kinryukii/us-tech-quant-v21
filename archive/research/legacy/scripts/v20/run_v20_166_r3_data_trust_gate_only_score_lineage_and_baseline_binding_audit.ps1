$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_166_r3_data_trust_gate_only_score_lineage_and_baseline_binding_audit.py"

python $Runner

