$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r3_r2_data_trust_direct_status_retest_after_materialization.py"

python $Runner
