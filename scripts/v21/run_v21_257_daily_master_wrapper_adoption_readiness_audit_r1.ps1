param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_257_daily_master_wrapper_adoption_readiness_audit_r1.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
& $Python @ArgsList
exit $LASTEXITCODE
