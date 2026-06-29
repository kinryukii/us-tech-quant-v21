Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $Dir "..\..")
Push-Location $Root
try { python (Join-Path $Dir "v21_075_r1_position_sizing_policy_builder.py"); exit $LASTEXITCODE }
finally { Pop-Location }
