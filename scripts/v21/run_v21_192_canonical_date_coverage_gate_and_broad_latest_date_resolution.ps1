$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $Root

python scripts/v21/v21_192_canonical_date_coverage_gate_and_broad_latest_date_resolution.py
