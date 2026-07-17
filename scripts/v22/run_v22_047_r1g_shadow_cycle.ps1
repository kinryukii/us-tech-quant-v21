[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
& $Python (Join-Path $RepoRoot "scripts\v22\v22_047_r1g_shadow_fractional_assumption_and_execution_arming.py") --repo-root $RepoRoot
exit $LASTEXITCODE
