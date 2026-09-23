$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_158_r1_reduced_shadow_score_recomputation_lineage_audit.py"

python $Runner

