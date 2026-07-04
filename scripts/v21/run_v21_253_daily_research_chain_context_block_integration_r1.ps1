param(
    [string]$RepoRoot = "D:\us-tech-quant",
    [string]$OutputDir = "",
    [string]$V21252Root = "",
    [string]$V21251Root = "",
    [string]$V21250Root = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "scripts\v21\v21_253_daily_research_chain_context_block_integration_r1.py"
$ArgsList = @($Script, "--repo-root", $RepoRoot)
if ($OutputDir) { $ArgsList += @("--output-dir", $OutputDir) }
if ($V21252Root) { $ArgsList += @("--v21-252-root", $V21252Root) }
if ($V21251Root) { $ArgsList += @("--v21-251-root", $V21251Root) }
if ($V21250Root) { $ArgsList += @("--v21-250-root", $V21250Root) }
& $Python @ArgsList
exit $LASTEXITCODE
