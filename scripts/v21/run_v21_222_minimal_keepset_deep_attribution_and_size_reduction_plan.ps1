param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) { $Python = $VenvPython } else { $Python = "python" }

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_222_minimal_keepset_deep_attribution_and_size_reduction_plan.py"),
    "--repo-root",
    $Root
)

& $Python @ArgsList
exit $LASTEXITCODE
