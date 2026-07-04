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
    (Join-Path $Root "scripts\v21\v21_215_cold_archive_zip_copy_creation_for_v21_154.py"),
    "--repo-root",
    $Root
)

& $Python @ArgsList
exit $LASTEXITCODE
