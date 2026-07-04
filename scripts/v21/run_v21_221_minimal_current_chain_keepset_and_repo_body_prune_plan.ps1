param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_221_minimal_current_chain_keepset_and_repo_body_prune_plan.py"),
    "--repo-root",
    $Root
)

& $Python @ArgsList
exit $LASTEXITCODE
