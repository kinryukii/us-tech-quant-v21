param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [switch]$DryRun,
    [switch]$Execute
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_261_daily_chain_retention_enforcement_wiring_r1.py"
$Mode = "DryRun"
if ($Execute) { $Mode = "Execute" }
$ArgsList = @($Script, "--repo-root", $RepoRoot, "--mode", $Mode)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
& $Python @ArgsList
exit $LASTEXITCODE
