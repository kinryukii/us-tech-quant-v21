[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Main = Join-Path $RepoRoot "scripts\v22\v22_047_r1d_live_market_account_bridge.py"
& $Python $Main status --repo-root $RepoRoot
exit $LASTEXITCODE

