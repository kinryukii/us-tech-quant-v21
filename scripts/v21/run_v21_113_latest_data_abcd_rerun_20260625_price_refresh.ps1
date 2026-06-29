$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root

python scripts/v21/v21_113_latest_data_abcd_rerun_20260625_price_refresh.py
