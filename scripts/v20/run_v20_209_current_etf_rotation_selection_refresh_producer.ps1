$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_209_current_etf_rotation_selection_refresh_producer.py"

python $Runner
