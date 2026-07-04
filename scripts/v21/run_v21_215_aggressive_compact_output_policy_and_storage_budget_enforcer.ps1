param(
    [string]$RepoRoot = "D:\us-tech-quant"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $RepoRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

$ArgsList = @(
    (Join-Path $Root "scripts\v21\v21_215_aggressive_compact_output_policy_and_storage_budget_enforcer.py"),
    "--repo-root",
    $Root
)

& $Python @ArgsList
exit $LASTEXITCODE
