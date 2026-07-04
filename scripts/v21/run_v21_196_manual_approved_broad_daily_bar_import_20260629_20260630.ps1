$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root
python scripts/v21/v21_196_manual_approved_broad_daily_bar_import_20260629_20260630.py
