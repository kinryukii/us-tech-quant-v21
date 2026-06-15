$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_199b_r3_shadow_dynamic_weight_candidate_and_guardrail_selection.py"

python $Runner
