$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_195_daily_snapshot_accumulation_and_forward_observation_ledger.py"

python $Runner
