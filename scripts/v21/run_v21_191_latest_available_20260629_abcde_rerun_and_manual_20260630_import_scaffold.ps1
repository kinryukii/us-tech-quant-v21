$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root

python scripts/v21/v21_191_latest_available_20260629_abcde_rerun_and_manual_20260630_import_scaffold.py
