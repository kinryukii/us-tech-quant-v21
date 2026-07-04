$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root

python scripts/v21/v21_190_alternate_daily_bar_source_for_20260630_and_safe_append.py
