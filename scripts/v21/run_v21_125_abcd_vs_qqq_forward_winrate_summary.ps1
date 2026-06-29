$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_125_abcd_vs_qqq_forward_winrate_summary.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.125 ABCD vs QQQ forward win-rate summary failed with exit code $LASTEXITCODE"
}
