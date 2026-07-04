$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root

python scripts/v21/v21_188_canonical_price_refresh_blocker_forensic_and_recovery.py
