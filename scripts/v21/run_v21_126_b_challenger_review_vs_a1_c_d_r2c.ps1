$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_126_b_challenger_review_vs_a1_c_d_r2c.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.126 B challenger review failed with exit code $LASTEXITCODE"
}
