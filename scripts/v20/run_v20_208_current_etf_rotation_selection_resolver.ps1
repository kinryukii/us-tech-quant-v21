$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_208_current_etf_rotation_selection_resolver.py"

python $Runner
