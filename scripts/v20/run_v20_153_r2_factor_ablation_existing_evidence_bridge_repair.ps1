$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_153_r2_factor_ablation_existing_evidence_bridge_repair.py"

python $Runner

