$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_169_data_trust_direct_ticker_level_mapping_repair.py"

python $Runner

