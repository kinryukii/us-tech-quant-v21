$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root
python scripts/v21/v21_196_r4_moomoo_sdk_opend_bootstrap_and_daily_kline_healthcheck.py
