$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_199b_r2_pit_lite_effectiveness_diagnostic_and_rank_quality_audit.py"

python $Runner
