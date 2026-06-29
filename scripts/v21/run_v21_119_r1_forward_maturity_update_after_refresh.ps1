$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_119_r1_forward_maturity_update_after_refresh.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.119_R1 forward maturity update after refresh failed with exit code $LASTEXITCODE"
}
