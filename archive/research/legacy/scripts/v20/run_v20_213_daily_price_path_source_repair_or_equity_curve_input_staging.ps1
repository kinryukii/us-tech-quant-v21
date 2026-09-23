$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "v20_213_daily_price_path_source_repair_or_equity_curve_input_staging.py"

python $Runner
