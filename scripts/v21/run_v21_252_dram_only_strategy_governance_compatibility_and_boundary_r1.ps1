param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$V21251Root = "",
    [string]$V21250Root = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_252_dram_only_strategy_governance_compatibility_and_boundary_r1.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($V21251Root) { $ArgsList += @("--v21-251-root", $V21251Root) }
if ($V21250Root) { $ArgsList += @("--v21-250-root", $V21250Root) }
& $Python @ArgsList
exit $LASTEXITCODE
