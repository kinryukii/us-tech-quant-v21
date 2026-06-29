$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_118_d_r2_repeated_loser_aware_design.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.118 D-R2 repeated loser aware design failed with exit code $LASTEXITCODE"
}
