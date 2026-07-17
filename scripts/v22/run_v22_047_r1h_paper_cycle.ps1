[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [switch]$StartupReset)
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$ArgsList = @((Join-Path $RepoRoot "scripts\v22\v22_047_r1h_paper_execution_order_lifecycle_and_reconciliation.py"), "--repo-root", $RepoRoot)
if ($StartupReset) { $ArgsList += "--startup-reset" }
& $Python @ArgsList
exit $LASTEXITCODE
