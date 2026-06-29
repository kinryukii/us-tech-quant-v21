$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$Script = Join-Path $Root "scripts\v21\v21_127_a1_primary_tracking_with_bc_diagnostic_watch.py"

Set-Location $Root
python $Script
if ($LASTEXITCODE -ne 0) {
    throw "V21.127 A1 primary tracking with B/C diagnostic watch failed with exit code $LASTEXITCODE"
}
