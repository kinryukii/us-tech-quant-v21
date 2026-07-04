param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_258_retention_guard_discovery_review_and_daily_entrypoint_unblock_r1.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
& $Python @ArgsList
exit $LASTEXITCODE
