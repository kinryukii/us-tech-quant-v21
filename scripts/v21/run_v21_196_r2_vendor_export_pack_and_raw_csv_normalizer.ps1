$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root
python scripts/v21/v21_196_r2_vendor_export_pack_and_raw_csv_normalizer.py
