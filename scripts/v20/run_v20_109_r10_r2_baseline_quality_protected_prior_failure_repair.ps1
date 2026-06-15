$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_109_r10_r2_baseline_quality_protected_prior_failure_repair.py"

python $Runner
