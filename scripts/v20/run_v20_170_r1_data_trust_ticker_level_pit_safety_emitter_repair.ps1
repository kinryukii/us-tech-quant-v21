$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_170_r1_data_trust_ticker_level_pit_safety_emitter_repair.py"

python $Runner

