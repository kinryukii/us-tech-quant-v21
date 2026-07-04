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

& $Python (Join-Path $Root "scripts\v21\v21_213_r2_moomoo_alt_env_reference_resolution_audit.py") --repo-root $Root
exit $LASTEXITCODE
