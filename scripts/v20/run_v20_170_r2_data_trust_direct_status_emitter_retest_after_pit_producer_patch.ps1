$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r2_data_trust_direct_status_emitter_retest_after_pit_producer_patch.py"

python $Runner
