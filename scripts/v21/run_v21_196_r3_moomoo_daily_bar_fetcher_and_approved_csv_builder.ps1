$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root
$Python = "python"
& $Python scripts/v21/v21_196_r3_moomoo_daily_bar_fetcher_and_approved_csv_builder.py
