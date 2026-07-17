[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [switch]$ProbeCapabilities)
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v22\v22_047_r1f_fractional_protected_sleeve.py"
$Arguments = @($Script, "--repo-root", $RepoRoot)
if ($ProbeCapabilities) { $Arguments += "--probe-capabilities" }
& $Python @Arguments
exit $LASTEXITCODE

