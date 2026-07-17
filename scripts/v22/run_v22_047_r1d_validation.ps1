[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Validator = Join-Path $RepoRoot "scripts\v22\validate_v22_047_r1d.py"
& $Python $Validator $RepoRoot
exit $LASTEXITCODE
