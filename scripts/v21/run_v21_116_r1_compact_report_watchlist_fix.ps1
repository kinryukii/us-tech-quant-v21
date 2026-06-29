$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_116_r1_compact_report_watchlist_fix.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.116 R1 compact report watchlist fix failed with exit code $LASTEXITCODE"
}
