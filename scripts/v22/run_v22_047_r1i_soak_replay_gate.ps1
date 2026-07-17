[CmdletBinding()]
param([string]$RepoRoot = "D:\us-tech-quant", [switch]$StartupReset, [switch]$Eod)
$ErrorActionPreference = "Stop"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { $Python = "python" }
$ArgsList = @((Join-Path $RepoRoot "scripts\v22\v22_047_r1i_paper_soak_replay_fault_injection_and_live_readiness_gate.py"), "--repo-root", $RepoRoot)
if ($StartupReset) { $ArgsList += "--startup-reset" }
if ($Eod) { $ArgsList += "--eod" }
& $Python @ArgsList
exit $LASTEXITCODE
