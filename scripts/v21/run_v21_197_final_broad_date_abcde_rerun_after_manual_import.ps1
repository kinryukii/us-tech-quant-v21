$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
if (-not $env:V21_197_TARGET_DATE) { $env:V21_197_TARGET_DATE = "2026-07-01" }
& $Python scripts/v21/v21_197_final_broad_date_abcde_rerun_after_manual_import.py
