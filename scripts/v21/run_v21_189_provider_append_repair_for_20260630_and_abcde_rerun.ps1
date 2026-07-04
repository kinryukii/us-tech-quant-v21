$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root

python scripts/v21/v21_189_provider_append_repair_for_20260630_and_abcde_rerun.py
